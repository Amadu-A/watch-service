# src/core/bootstrap.py
"""Операционные helpers единственного watch.sh: секреты, assets и shared RabbitMQ provisioning."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import urllib.request

from cryptography.fernet import Fernet
from dotenv import dotenv_values

from core.config import ROOT, Settings


def init_environment() -> None:
    """Создаёт только отсутствующий sparse .env; существующие deployment secrets сохраняются."""
    path = ROOT / ".env"
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
        file.write("# Приватные значения. Остальной baseline загружается из .env.example.\n")
        for key, value in values.items():
            file.write(f"{key}={value}\n")
    print("Создан sparse .env; секретные значения не выводятся.")


def download_model() -> None:
    """Загружает baseline pretrained weights в ignored models, без установки YOLO на host."""
    path = ROOT / Settings().vision_model
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError("VISION_MODEL должен находиться в папке проекта")
    if path.exists():
        print("Weights уже существуют; файл не перезаписан.")
        return
    if path.name != "yolo11n.pt":
        raise ValueError("Автозагрузка поддерживает yolo11n.pt; другую модель положите вручную")
    path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
    with urllib.request.urlopen(url, timeout=120) as response:
        content = response.read()
    if len(content) < 100000:
        raise RuntimeError("Не удалось получить model weights")
    path.write_bytes(content)
    print(f"Baseline yolo11n.pt загружен; SHA256: {hashlib.sha256(content).hexdigest()}")


def provision_rabbitmq(container: str) -> None:
    """Создаёт только project vhost/user через rabbitmqctl выбранного shared контейнера."""
    config = Settings()
    user, vhost = config.rabbitmq_user, config.rabbitmq_vhost
    if not user.startswith("warehouse") or not vhost.startswith("warehouse"):
        raise ValueError("Provisioning разрешён только для warehouse namespace")
    password = config.rabbitmq_password.get_secret_value()
    if not password:
        raise ValueError("Задайте RABBITMQ_PASSWORD")

    network = (
        os.environ.get("SHARED_NETWORK")
        or dotenv_values(ROOT / ".env").get("SHARED_NETWORK")
        or dotenv_values(ROOT / ".env.example")["SHARED_NETWORK"]
    )
    networks = json.loads(
        subprocess.run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout
    )
    if network not in networks:
        subprocess.run(
            ["docker", "network", "connect", "--alias", config.rabbitmq_host, network, container],
            check=True,
        )
    else:
        aliases = networks[network].get("Aliases") or []
        if config.rabbitmq_host not in aliases and config.rabbitmq_host != container:
            raise ValueError(
                "RabbitMQ уже в сети без нужного alias: "
                "задайте RABBITMQ_HOST равным имени контейнера"
            )

    def control(*args, capture=False):
        """Передаёт argv без shell и скрывает вывод команд, содержащих пароль."""
        try:
            return subprocess.run(
                ["docker", "exec", container, "rabbitmqctl", *args],
                check=True,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            ).stdout
        except subprocess.CalledProcessError:
            raise RuntimeError("rabbitmq_control_failed") from None

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
        "^warehouse\\..*",
        "^warehouse\\..*",
        "^warehouse\\..*",
    )
    print("Project vhost/user настроены. Shared сервисы не перезапускались.")


def main() -> None:
    """Разбирает операцию watch.sh, не исполняя произвольный пользовательский shell."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "model", "rabbit", "value"])
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if args.action == "init":
        init_environment()
    elif args.action == "model":
        download_model()
    elif args.action == "rabbit":
        if not args.argument:
            raise ValueError("Передайте имя shared RabbitMQ container из discover")
        provision_rabbitmq(args.argument)
    else:
        # Только несекретные значения для script dispatch; произвольные secrets читать нельзя.
        allowed = {"SHARED_NETWORK", "WEB_PORT", "VISION_DEVICE", "APP_ENV"}
        if args.argument not in allowed:
            raise ValueError("Недопустимое имя параметра")
        values = {
            **dotenv_values(ROOT / ".env.example"),
            **dotenv_values(ROOT / ".env"),
            **os.environ,
        }
        print(values.get(args.argument, ""))


if __name__ == "__main__":
    main()
