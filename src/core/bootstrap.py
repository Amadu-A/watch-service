# src/core/bootstrap.py
"""Подготовка окружения и проверка проектного доступа к общему RabbitMQ."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from amqp.exceptions import AMQPError
from cryptography.fernet import Fernet
from kombu import Connection

from core.config import ROOT, Settings


def operations_root() -> Path:
    """Возвращает корень проекта, примонтированный в служебный контейнер."""
    return Path(os.environ.get("WATCH_OPERATIONS_ROOT", ROOT))


def init_environment() -> None:
    """Создаёт только отсутствующий sparse .env; существующие deployment secrets сохраняются."""
    path = operations_root() / ".env"
    if path.exists():
        print(".env уже существует; значения сохранены.")
        return
    values = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
        "CAMERA_CREDENTIALS_KEY": Fernet.generate_key().decode(),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "RABBITMQ_PASSWORD": secrets.token_urlsafe(32),
    }
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.write("# Секреты окружения; постоянные значения заданы в Settings.\n")
        file.write("APP_ENV=production\n")
        for key, value in values.items():
            file.write(f"{key}={value}\n")
    print("Создан sparse .env; секретные значения не выводятся.")


def docker_command(*arguments: str, capture: bool = False) -> str:
    """Выполняет Docker без shell и скрывает вывод, который может содержать секреты."""
    try:
        result = subprocess.run(
            ["docker", *arguments],
            check=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        raise RuntimeError(
            f"Не удалось выполнить Docker {arguments[0]}; проверьте имя контейнера и Docker socket."
        ) from None
    return result.stdout or ""


def wait_for_rabbitmq(container: str, timeout_seconds: float = 30) -> None:
    """Ожидает готовности уже запущенного shared брокера без управления его lifecycle."""
    deadline = time.monotonic() + timeout_seconds
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "rabbitmq-diagnostics",
                    "-q",
                    "--timeout",
                    "5",
                    "check_running",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=min(5, remaining),
            )
            if result.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))
    raise RuntimeError(
        f"RabbitMQ в {container} не готов за {timeout_seconds:g} секунд. "
        f"Проверьте docker logs --tail=100 {container}."
    )


def check_broker() -> None:
    """Проверяет DNS, AMQP-вход и проектный vhost из общей сети контейнеров."""
    config = Settings()
    network = os.environ.get("SHARED_NETWORK", "ai-shared")
    try:
        with Connection(
            hostname=config.rabbitmq_host,
            port=config.rabbitmq_port,
            userid=config.rabbitmq_user,
            password=config.rabbitmq_password.get_secret_value(),
            virtual_host=config.rabbitmq_vhost,
            connect_timeout=5,
        ) as broker:
            broker.ensure_connection(max_retries=0, reraise_as_library_errors=False)
    except socket.gaierror:
        raise RuntimeError(
            f"RabbitMQ: имя {config.rabbitmq_host} не разрешается в сети {network}. "
            "Проверьте shared stack; выполните bash scripts/watch.sh rabbit ИМЯ_КОНТЕЙНЕРА."
        ) from None
    except AMQPError as error:
        raise RuntimeError(
            f"RabbitMQ: AMQP-вход в vhost {config.rabbitmq_vhost} отклонён "
            f"({type(error).__name__}). Повторите watch.sh rabbit с паролем из .env."
        ) from None
    except OSError:
        raise RuntimeError(
            f"RabbitMQ: {config.rabbitmq_host}:{config.rabbitmq_port} недоступен. "
            "Проверьте shared брокер и AMQP listener."
        ) from None
    print(f"RabbitMQ: AMQP-доступ к {config.rabbitmq_host}/{config.rabbitmq_vhost} проверен.")


def provision_rabbitmq(container: str) -> None:
    """Проверяет shared брокер и настраивает только проектные vhost, пользователя и права."""
    config = Settings()
    user, vhost = config.rabbitmq_user, config.rabbitmq_vhost
    if not user.startswith("warehouse") or not vhost.startswith("warehouse"):
        raise ValueError("Provisioning разрешён только для warehouse namespace")
    password = config.rabbitmq_password.get_secret_value()
    if not password:
        raise ValueError("Задайте RABBITMQ_PASSWORD")
    state = json.loads(
        docker_command("inspect", "--format", "{{json .State}}", container, capture=True)
    )
    if not state.get("Running"):
        raise RuntimeError(
            f"RabbitMQ: {container} имеет состояние {state.get('Status')}. "
            "Запустите брокер из shared-infrastructure, затем повторите watch.sh rabbit."
        )
    wait_for_rabbitmq(container)
    network = os.environ.get("SHARED_NETWORK", "ai-shared")
    networks = json.loads(
        docker_command(
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            container,
            capture=True,
        )
    )
    if network not in networks:
        docker_command("network", "connect", "--alias", config.rabbitmq_host, network, container)
    else:
        names = [
            *(networks[network].get("Aliases") or []),
            *(networks[network].get("DNSNames") or []),
        ]
        if config.rabbitmq_host not in names and config.rabbitmq_host != container:
            raise ValueError(
                f"RabbitMQ в сети {network} без имени {config.rabbitmq_host}: "
                f"задайте RABBITMQ_HOST={container} в .env."
            )

    def control(*args: str, capture: bool = False) -> str:
        """Передаёт argv и сообщает только имя неудачной команды, исключая пароль."""
        try:
            return docker_command("exec", container, "rabbitmqctl", *args, capture=capture)
        except RuntimeError:
            raise RuntimeError(
                f"RabbitMQ: команда {args[0]} не выполнена в {container}. "
                f"Проверьте docker logs --tail=100 {container}."
            ) from None

    users = control("list_users", "--silent", capture=True)
    vhosts = control("list_vhosts", "--silent", capture=True)
    if vhost not in vhosts.splitlines():
        control("add_vhost", vhost)
    if user not in {line.split()[0] for line in users.splitlines() if line.strip()}:
        control("add_user", user, password)
    else:
        control("change_password", user, password)
    control(
        "set_permissions",
        "-p",
        vhost,
        user,
        r"^warehouse\..*",
        r"^warehouse\..*",
        r"^warehouse\..*",
    )
    print("Проектные vhost, пользователь и права RabbitMQ настроены.")


def main() -> None:
    """Разбирает операцию watch.sh без выполнения произвольного shell."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "rabbit", "value", "check", "check-broker"])
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if args.action == "init":
        init_environment()
    elif args.action == "rabbit":
        if not args.argument:
            raise ValueError("Передайте имя shared RabbitMQ container из discover")
        provision_rabbitmq(args.argument)
    elif args.action == "check-broker":
        check_broker()
    elif args.action == "check":
        config = Settings()
        if config.app_env != "production":
            raise ValueError("Для сервера задайте APP_ENV=production")
        for name in ("postgres_password", "rabbitmq_password", "camera_credentials_key"):
            if not getattr(config, name).get_secret_value():
                raise ValueError(f"Отсутствует обязательный секрет: {name.upper()}")
        if not config.django_secure_cookies:
            raise ValueError("В production требуются защищённые cookies")
        print("Конфигурация production проверена; секреты не выводятся.")
    elif args.argument == "SHARED_NETWORK":
        print(os.environ.get("SHARED_NETWORK", "ai-shared"))
    elif args.argument == "VISION_ENABLED":
        print(str(Settings().vision_enabled).lower())
    else:
        raise ValueError("Недопустимое имя параметра")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
