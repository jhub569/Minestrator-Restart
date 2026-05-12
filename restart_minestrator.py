name: Minestrator-Restart

on:
  workflow_dispatch:
  #schedule:
    #- cron: '0 1 * * *'
    #- cron: '0 5 * * *'
    #- cron: '0 9 * * *'
    #- cron: '0 13 * * *'
  # --- 新增：接收来自 Uptime Kuma 的 Webhook 信号 ---
  repository_dispatch:
    types: [tunnel_offline]

jobs:
  run_minestrator_restart:
    runs-on: ubuntu-latest
    steps:
      - name: 📥 下载代码
        uses: actions/checkout@v4

      - name: 🐍 设置 Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: 🛡️ 启动 Xray 代理转发
        env:
          XRAY_CONFIG: ${{ secrets.XRAY_CONFIG_JSON }}
        run: |
          wget -q https://github.com/XTLS/Xray-core/releases/download/v25.12.8/Xray-linux-64.zip
          unzip -q Xray-linux-64.zip -d xray-core
          echo "$XRAY_CONFIG" > xray-core/config.json
          cd xray-core
          nohup ./xray run -c config.json > xray.log 2>&1 &
          sleep 10
          echo "✅ 代理已在后台启动"

      - name: 🛠️ 安装依赖
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb x11-utils xdotool scrot
          pip install seleniumbase
          seleniumbase install chromedriver
          seleniumbase install chrome

      - name: 🚀 运行脚本
        env:
          PYTHONIOENCODING: utf-8
          MINESTRATOR_ACCOUNT: ${{ secrets.MINESTRATOR_ACCOUNT }}
          MINESTRATOR_SERVER_ID: ${{ secrets.MINESTRATOR_SERVER_ID }}
          MINESTRATOR_AUTH: ${{ secrets.MINESTRATOR_AUTH }}
          TG_BOT: ${{ secrets.TG_BOT }}
          HTTP_PROXY: http://127.0.0.1:8080
          HTTPS_PROXY: http://127.0.0.1:8080
          # 将 Webhook 传来的状态映射为环境变量，方便 Python 脚本读取（可选）
          KUMA_STATUS: ${{ github.event.client_payload.status }}
        run: |
          xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" \
          python restart_minestrator.py --proxy=http://127.0.0.1:8080

      - name: 📸 上传截图
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: debug-screenshots
          path: "*.png"
