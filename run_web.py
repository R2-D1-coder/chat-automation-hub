"""
启动 Web 管理界面

使用方法：
    python run_web.py

访问地址：
    本地：http://localhost:5000
    远程：http://<你的IP>:5000
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.app import create_app

if __name__ == "__main__":
    print("=" * 60)
    print("微信群发管理中心")
    print("=" * 60)
    print(f"本地访问: http://localhost:5000")
    print(f"远程访问: http://<你的IP>:5000")
    print("=" * 60)
    print("按 Ctrl+C 停止服务")
    print()
    
    app = create_app()
    # 允许远程访问，开启调试模式查看详细错误
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

