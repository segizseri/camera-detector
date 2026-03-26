# Laptop AI Box (Hikvision-First MVP)

A lightweight AI-powered video surveillance solution designed to run on a laptop and connect to an existing NVR/DVR setup (optimized for Hikvision). It ingests RTSP streams, transcodes them to HLS for web viewing, and runs local AI (YOLO) to detect people, fights, and camera downtime.

## Features
- **NVR Auto-Discovery**: Import cameras from Hikvision NVRs automatically via UI.
- **RTSP Testing**: Quickly diagnose connection issues directly from the dashboard.
- **Local AI Processing**: YOLOv8-powered person & fight detection directly from RTSP streams.
- **Webhooks**: Forward critical alerts (with snapshots) to external services.
- **HLS Web Viewer**: Access camera streams in the browser efficiently.
- **Event Recording**: Saves snapshots and short clips around the time of the event.

## 🚀 Развертывание (Deployment)

### 1. Подготовка чистого ноутбука (Ubuntu 22.04/24.04)
Если у вас "чистый" ноутбук (свежеустановленная Ubuntu), сначала установите Docker и Docker Compose. Откройте терминал (`Ctrl+Alt+T`) и поочередно выполните команды:

```bash
# 1. Обновите список пакетов
sudo apt-get update

# 2. Установите необходимые зависимости
sudo apt-get install -y ca-certificates curl gnupg

# 3. Добавьте официальный GPG-ключ Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. Добавьте репозиторий Docker
echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. Обновите пакеты и установите Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 6. Установите права (чтобы запускать docker без sudo)
sudo usermod -aG docker $USER
# После выполнения этой команды нужно перезайти в систему (или выполнить `su - $USER`)
```

### 2. Запуск приложения

1. Перейдите в папку проекта:
   ```bash
   cd /home/user/projects/camera-detector
   ```
2. Запустите контейнеры в фоновом режиме:
   ```bash
   docker compose up -d --build
   ```
3. Откройте веб-панель в браузере по адресу: [http://localhost:4000](http://localhost:4000) (Логин/Пароль по умолчанию: **admin** / **admin**).

## 📹 Подключение камер (Hikvision NVR)
1. В настройках вашего видеорегистратора (NVR) включите RTSP (`Network > Advanced Settings > Network Service > RTSP`).
2. Создайте пользователя (например, `ai_box`) с правами **только на просмотр** ("Live View") для безопасности.
3. В веб-панели приложения ([http://localhost:4000](http://localhost:4000)) перейдите в раздел "NVR Setup".
4. Введите IP-адрес, логин и пароль. 
   - **Stream Profile**: Рекомендуется выбрать **"Substream"** (дополнительный поток). Это значительно ускорит работу ИИ (YOLO) без потери качества аналитики.
5. Нажмите **Test Connection** для проверки подключения.
6. Нажмите **Import Cameras**, чтобы добавить камеры в систему для анализа потока.

## RTSP Testing Details
You can verify the RTSP stream in VLC Media Player using the following structure:
- **Main Stream**: `rtsp://user:password@IP:554/Streaming/Channels/{channel}01`
- **Sub Stream**: `rtsp://user:password@IP:554/Streaming/Channels/{channel}02`

## Troubleshooting

- **No frames / Black Screen in Web**:
  - Check if the HLS segments are being generated in `./data/media/hls/`. 
  - Ensure the NVR isn't dropping the TCP connection. Try limiting the FPS limit in Camera Settings.
- **Wrong Password / Authentication Failed**:
  - Verify that the specific user has "Live View" permissions for the target cameras. 
  - RTSP limits special characters in passwords. Ensure your password is URL-encoded if it contains characters like `@` or `#`.
- **Firewall Issues**:
  - The laptop must be on the same subnet as the NVR, or have rules allowing inbound traffic on TCP `554` (RTSP) and `8000/8080` (HTTP).
- **RTSP over TCP**:
  - By default, we use RTSP over TCP for stability. If your generic NVR does not support TCP via interleaved mode, it will cause artifacts or fail. The system provides a toggle in the import dialogue.
