# KVM Windows + RustDesk 部署指南

> 支持 Windows 10 / Windows 11

## 服务器配置

| 项目 | 配置 |
|------|------|
| 服务器 IP | `159.69.60.143` |
| CPU | AMD Ryzen 9 7950X3D (16核32线程) |
| 内存 | 124GB (可用约63GB) |
| 虚拟化 | KVM 已启用 ✅ |
| 磁盘 | 剩余约 46GB (需清理或使用外置存储) |

## 推荐虚拟机配置

| 项目 | 推荐值 | 说明 |
|------|--------|------|
| vCPU | 4-8 | 日常办公 4 核够用 |
| 内存 | 8-16GB | RustDesk + 办公软件 8GB 足够 |
| 磁盘 | 60-80GB | Windows 基础约 25-30GB + 软件空间 |

---

## 1. 环境准备（已完成）

```bash
# 已安装的包
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients virtinst ovmf

# 服务已启动
sudo systemctl enable --now libvirtd

# 验证
virsh list --all
```

### 添加用户权限（避免每次 sudo）

```bash
sudo usermod -aG libvirt,kvm $USER
newgrp libvirt
```

---

## 2. 准备 ISO 文件

### 2.1 创建目录

```bash
sudo mkdir -p /var/lib/libvirt/iso /var/lib/libvirt/images
sudo chown -R $USER:$USER /var/lib/libvirt/iso
```

### 2.2 下载/上传 ISO

需要两个文件：

| 文件 | 说明 | 下载地址 |
|------|------|----------|
| Windows ISO | Win10 或 Win11 官方镜像 | [Win10](https://www.microsoft.com/software-download/windows10ISO) / [Win11](https://www.microsoft.com/software-download/windows11) |
| `virtio-win.iso` | VirtIO 驱动 | [Fedora 项目](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso) |

#### 方法一：使用 qBittorrent 下载（推荐）

服务器已安装 qBittorrent-nox，可以通过 WebUI 下载种子。

**1. 建立 SSH 隧道访问 WebUI**

在本地电脑执行：

```bash
ssh -L 8080:127.0.0.1:8080 root@159.69.60.143
```

**2. 打开浏览器访问**

```
http://127.0.0.1:8080
```

默认登录信息：
- 用户名：`admin`
- 密码：首次启动时查看日志 `journalctl -u qbittorrent-nox | grep password`

**3. 设置下载路径**

在 WebUI 中：设置 → 下载 → 默认保存路径 → `/var/lib/libvirt/iso`

**4. 添加种子下载 Windows ISO**

- 从 PT 站点或其他来源获取 Windows ISO 种子
- 在 WebUI 点击"添加种子"上传 .torrent 文件
- 等待下载完成

**5. 下载完成后重命名**

```bash
# 进入下载目录
cd /var/lib/libvirt/iso

# 查看下载的文件
ls -la

# 重命名为标准名称（根据实际文件名修改）
mv "zh-cn_windows_11_business_editions_version_23h2_updated_sep_2024/x64_dvd_22316bf2.iso" win11.iso
# 或
mv "windows_10_xxx.iso" win10.iso
```

#### 方法二：从本地上传

```bash
scp windows.iso virtio-win.iso root@159.69.60.143:/var/lib/libvirt/iso/
```

#### 下载 VirtIO 驱动

在服务器直接下载：

```bash
cd /var/lib/libvirt/iso
wget https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso
```

### 2.3 qBittorrent 安装（如果未安装）

```bash
# 安装 qBittorrent-nox（无界面版本）
apt install -y qbittorrent-nox

# 创建 systemd 服务
cat > /etc/systemd/system/qbittorrent-nox.service << 'EOF'
[Unit]
Description=qBittorrent-nox Daemon Service
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/qbittorrent-nox --webui-port=8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 启动并设置开机自启
systemctl daemon-reload
systemctl enable --now qbittorrent-nox

# 查看临时密码
journalctl -u qbittorrent-nox | grep password
```

---

## 3. 创建虚拟磁盘

```bash
# 创建 80GB 的 qcow2 磁盘（实际占用空间按使用量增长）
# Win10:
qemu-img create -f qcow2 /var/lib/libvirt/images/win10.qcow2 80G

# Win11:
qemu-img create -f qcow2 /var/lib/libvirt/images/win11.qcow2 80G
```

---

## 4. 创建并启动虚拟机

### 4.1 Windows 10 安装命令

```bash
virt-install \
  --name win10 \
  --memory 8192 \
  --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/var/lib/libvirt/images/win10.qcow2,format=qcow2,bus=virtio,cache=writeback \
  --cdrom /var/lib/libvirt/iso/win10.iso \
  --disk /var/lib/libvirt/iso/virtio-win.iso,device=cdrom \
  --os-variant win10 \
  --network network=default,model=virtio \
  --graphics vnc,listen=127.0.0.1,port=5901 \
  --boot uefi \
  --noautoconsole
```

### 4.2 Windows 11 安装命令

```bash
virt-install \
  --name win11 \
  --memory 8192 \
  --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/var/lib/libvirt/images/win11.qcow2,format=qcow2,bus=virtio,cache=writeback \
  --cdrom /var/lib/libvirt/iso/win11.iso \
  --disk /var/lib/libvirt/iso/virtio-win.iso,device=cdrom \
  --os-variant win11 \
  --network network=default,model=virtio \
  --graphics vnc,listen=127.0.0.1,port=5901 \
  --boot uefi \
  --noautoconsole
```

**参数说明：**
- `--memory 8192`: 8GB 内存
- `--vcpus 4`: 4 个虚拟 CPU
- `--cpu host-passthrough`: 直通宿主机 CPU 特性，性能最佳
- `--bus=virtio`: 使用 VirtIO 磁盘，性能更好
- `--cache=writeback`: 启用写缓存，提升磁盘性能
- `--graphics vnc,listen=127.0.0.1,port=5901`: VNC 只监听本地，安全
- `--boot uefi`: 使用 UEFI 启动

### 4.3 检查虚拟机状态

```bash
virsh list --all
virsh vncdisplay win11   # 查看 VNC 端口
```

---

## 5. 通过 VNC 完成 Windows 安装

### 5.1 建立 SSH 隧道（必须！）

> ⚠️ **重要**：VNC 只监听服务器本地 127.0.0.1，不能直接连接服务器 IP！必须先建立 SSH 隧道。

在**你的本地电脑**打开终端/CMD/PowerShell，执行：

```bash
ssh -L 5901:127.0.0.1:5901 root@159.69.60.143
```

输入密码登录后，**保持这个窗口打开不要关闭**。

### 5.2 连接 VNC

打开 VNC 客户端，连接到：

```
127.0.0.1:5901
```

> ⚠️ 注意：连接的是 `127.0.0.1`（你的本地电脑），**不是** `159.69.60.143`！
> SSH 隧道会自动把本地 5901 端口转发到服务器。

**推荐的 VNC 客户端：**

| 系统 | 推荐软件 |
|------|----------|
| Windows | TigerVNC、TightVNC |
| macOS | RealVNC Viewer、TigerVNC |
| Linux | Remmina、TigerVNC |

### 5.3 UEFI 启动菜单操作

连接 VNC 后，你会看到 UEFI 启动菜单：

1. 用 **↑↓ 键** 选择 **Boot Manager**，按 **Enter**
2. 在启动设备列表中，选择 **UEFI QEMU DVD-ROM QM00001**（这是 Windows ISO）
3. 按 **Enter**
4. **立即疯狂按空格键或任意键**（必须快！否则会跳回菜单）

> 💡 如果又回到了启动菜单，说明没来得及按键，重复上述步骤并更快地按键。

### 5.4 安装时找不到硬盘？加载 VirtIO 驱动

到"选择安装位置"界面，如果看不到硬盘：

1. 点击 **"加载驱动程序"**
2. 点击 **"浏览"**
3. 找到 VirtIO 光盘（通常是 D: 或 E: 盘）
4. 导航到对应目录：
   - **Windows 10**: `viostor → w10 → amd64`
   - **Windows 11**: `viostor → w11 → amd64`
5. 选择 **Red Hat VirtIO SCSI controller** 驱动
6. 点击 **"下一页"**
7. 硬盘会出现在列表中

### 5.5 Windows 11 OOBE 跳过网络要求

Windows 11 安装过程中会要求联网，但此时 VirtIO 网卡驱动还未加载，会卡在"让我们为你连接到网络"界面。

**解决方法：**

按 **Shift + F10** 打开命令提示符，输入：

```cmd
oobe\bypassnro
```

按 Enter 后系统会自动重启，重启后会出现 **"我没有 Internet 连接"** 的选项，点击它即可跳过联网继续安装。

> 💡 进入桌面后安装 `virtio-win-guest-tools.exe`，网络会自动连接。

---

## 6. Windows 首次进桌面后的配置

### 6.1 安装 VirtIO 完整驱动

1. 打开 VirtIO 光盘（D: 或 E:）
2. 运行 `virtio-win-guest-tools.exe`
3. 安装完成后**重启**

### 6.2 电源设置（重要！）

防止远控时黑屏/断连：

1. **控制面板 → 电源选项 → 更改计划设置**
2. 关闭显示器：**从不**
3. 使计算机进入睡眠：**从不**

4. **高级电源设置 → 睡眠 → 休眠**：**关闭**

5. **关闭快速启动**：
   - 控制面板 → 电源选项 → 选择电源按钮的功能
   - 点击"更改当前不可用的设置"
   - 取消勾选"启用快速启动"

---

## 7. 安装 RustDesk（无人值守远控）

### 7.1 一键部署脚本（推荐）

Windows 安装完成进入桌面后，打开 **PowerShell（管理员）**，执行以下脚本：

```powershell
# RustDesk 一键部署脚本（含自建服务器配置）
$rustdeskUrl = "https://github.com/rustdesk/rustdesk/releases/download/1.3.6/rustdesk-1.3.6-x86_64.exe"
$installer = "$env:TEMP\rustdesk.exe"

# 配置信息
$password = "525611Ydh"
$idServer = "47.100.244.180"
$relayServer = "47.100.244.180"
$key = "525611"

Write-Host "下载 RustDesk..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $rustdeskUrl -OutFile $installer

Write-Host "安装 RustDesk..." -ForegroundColor Cyan
Start-Process -FilePath $installer -ArgumentList "--silent-install" -Wait
Start-Sleep -Seconds 5

Write-Host "配置自建服务器..." -ForegroundColor Cyan
$configPath = "$env:APPDATA\RustDesk\config\RustDesk2.toml"
$configDir = Split-Path $configPath
if (!(Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir -Force }

@"
rendezvous_server = '$idServer'
relay_server = '$relayServer'
key = '$key'
"@ | Out-File -FilePath $configPath -Encoding UTF8

Write-Host "设置固定密码..." -ForegroundColor Cyan
& "C:\Program Files\RustDesk\rustdesk.exe" --password $password

Write-Host "获取 RustDesk ID:" -ForegroundColor Green
& "C:\Program Files\RustDesk\rustdesk.exe" --get-id

Remove-Item $installer -Force
Write-Host "部署完成！记录上面的 ID 用于远程连接。" -ForegroundColor Green
```

**执行完成后记录输出的 RustDesk ID！**

### 7.2 手动安装方式

如果脚本执行失败，可以手动安装：

1. 下载 RustDesk：https://rustdesk.com/
2. 选择 **安装版**（不是便携版）
3. 安装完成后打开 RustDesk
4. 点击右侧 **"安装服务"**（开机自启）
5. 进入 **设置 → 安全** → 设置固定密码：`525611Ydh`
6. 进入 **设置 → 网络** → ID/中继服务器：
   - ID 服务器：`47.100.244.180`
   - 中继服务器：`47.100.244.180`
   - Key：`525611`
7. **记录你的 RustDesk ID**

### 7.3 自建服务器配置

| 项目 | 值 |
|------|-----|
| ID 服务器 | `47.100.244.180` |
| 中继服务器 | `47.100.244.180` |
| Key | `525611` |
| 固定密码 | `525611Ydh` |

---

## 8. 宿主机管理命令

### 8.1 设置开机自启

```bash
virsh autostart win11
```

### 8.2 常用命令

```bash
# 查看所有虚拟机
virsh list --all

# 启动虚拟机
virsh start win11

# 正常关机（需要 QEMU Guest Agent）
virsh shutdown win11

# 强制关机（相当于拔电源，慎用）
virsh destroy win11

# 重启
virsh reboot win11

# 暂停/恢复
virsh suspend win11
virsh resume win11

# 查看 VNC 端口
virsh vncdisplay win11

# 编辑虚拟机配置
virsh edit win11

# 删除虚拟机（不删除磁盘）
virsh undefine win11

# 删除虚拟机（同时删除磁盘）
virsh undefine win11 --remove-all-storage
```

### 8.3 快照管理

```bash
# 创建快照
virsh snapshot-create-as win11 --name "clean-install" --description "刚装完系统"

# 查看快照
virsh snapshot-list win11

# 恢复快照
virsh snapshot-revert win11 --snapshotname "clean-install"

# 删除快照
virsh snapshot-delete win11 --snapshotname "clean-install"
```

---

## 9. 网络说明

### 当前使用：NAT 模式（推荐）

- Windows 可以访问外网 ✅
- RustDesk 正常工作 ✅
- 宿主机安全 ✅
- 配置简单 ✅

### 如果需要桥接（高级）

桥接可以让虚拟机获得局域网 IP，但配置风险较大（可能断网）。

只有以下情况才需要桥接：
- 需要从局域网其他机器直接 RDP 到 Windows
- 需要 SMB 文件共享

---

## 10. 安全建议

| 项目 | 建议 |
|------|------|
| VNC | ✅ 只监听 127.0.0.1，通过 SSH 隧道访问 |
| RDP | ❌ 不要暴露公网 |
| RustDesk | ✅ 设置强密码 |
| 防火墙 | 宿主机只开必要端口 |

---

## 11. 故障排查

### VNC 连不上

```bash
# 检查虚拟机是否运行
virsh list --all

# 检查 VNC 端口
virsh vncdisplay win11

# 检查端口监听
ss -tlnp | grep 5901
```

**常见错误**：直接用 VNC 连接 `159.69.60.143:5901` → 错误！必须先建立 SSH 隧道，然后连接 `127.0.0.1:5901`

### 虚拟机启动失败

```bash
# 查看详细错误
virsh start win11 --console

# 查看 libvirt 日志
sudo journalctl -u libvirtd -f
```

### 磁盘空间不足

```bash
# 检查 qcow2 实际大小
qemu-img info /var/lib/libvirt/images/win11.qcow2

# 压缩 qcow2（需要关机）
virsh shutdown win11
qemu-img convert -O qcow2 win11.qcow2 win11-compressed.qcow2
```

### UEFI 启动菜单反复跳回

选择 DVD-ROM 后必须**立即疯狂按任意键**，响应 "Press any key to boot from CD" 提示。

---

## 12. 性能优化（可选）

### 12.1 启用大页内存

```bash
# 编辑虚拟机配置
virsh edit win11

# 在 <memoryBacking> 添加：
<memoryBacking>
  <hugepages/>
</memoryBacking>
```

### 12.2 CPU 固定（大负载场景）

```bash
# 在 <cputune> 添加 CPU 绑定
<cputune>
  <vcpupin vcpu='0' cpuset='0'/>
  <vcpupin vcpu='1' cpuset='1'/>
  <vcpupin vcpu='2' cpuset='2'/>
  <vcpupin vcpu='3' cpuset='3'/>
</cputune>
```

### 12.3 调整显示分辨率

默认显卡是 bochs，显存只有 16MB，分辨率受限（最高 1280x800）。

#### 方法一：安装 VirtIO 驱动

进入 Windows 后：

1. 打开 VirtIO 光盘（D: 或 E:）
2. 运行 `virtio-win-guest-tools.exe`
3. 安装完成后重启
4. 设置 → 系统 → 屏幕 → 调整分辨率

#### 方法二：更换为 QXL 显卡（推荐，支持更高分辨率）

在宿主机执行以下命令：

```bash
# 1. 关闭虚拟机
virsh shutdown win11
sleep 5

# 2. 导出配置
virsh dumpxml win11 > /tmp/win11.xml

# 3. 修改显卡：bochs -> qxl，显存增加到 64MB
sed -i "s/<model type='bochs' vram='16384' heads='1' primary='yes'\/>/<model type='qxl' ram='65536' vram='65536' vgamem='16384' heads='1' primary='yes'\/>/" /tmp/win11.xml

# 4. 应用配置
virsh define /tmp/win11.xml

# 5. 启动虚拟机
virsh start win11
```

修改后支持的分辨率：
- 1920x1080
- 1920x1200
- 2560x1440
- 2560x1600
- 以及更多...

> 💡 修改显卡后，Windows 可能需要重新安装 VirtIO 显卡驱动，运行 `virtio-win-guest-tools.exe` 即可。

---

## 快速部署脚本

```bash
#!/bin/bash
# 一键部署脚本（ISO 文件需要提前准备好）

set -e

# 配置变量（根据需要修改）
WIN_VERSION="win11"  # 可选: win10 或 win11
ISO_FILE="/var/lib/libvirt/iso/${WIN_VERSION}.iso"
DISK_FILE="/var/lib/libvirt/images/${WIN_VERSION}.qcow2"
VIRTIO_ISO="/var/lib/libvirt/iso/virtio-win.iso"

# 检查 Windows ISO
if [ ! -f "$ISO_FILE" ]; then
    echo "请先上传 ${WIN_VERSION}.iso 到 /var/lib/libvirt/iso/"
    exit 1
fi

# 下载 VirtIO 驱动
if [ ! -f "$VIRTIO_ISO" ]; then
    echo "下载 VirtIO 驱动..."
    wget -O "$VIRTIO_ISO" \
        https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso
fi

# 创建磁盘
echo "创建虚拟磁盘..."
qemu-img create -f qcow2 "$DISK_FILE" 80G

# 创建虚拟机
echo "创建虚拟机..."
virt-install \
  --name "$WIN_VERSION" \
  --memory 8192 \
  --vcpus 4 \
  --cpu host-passthrough \
  --disk path="$DISK_FILE",format=qcow2,bus=virtio,cache=writeback \
  --cdrom "$ISO_FILE" \
  --disk "$VIRTIO_ISO",device=cdrom \
  --os-variant "$WIN_VERSION" \
  --network network=default,model=virtio \
  --graphics vnc,listen=127.0.0.1,port=5901 \
  --boot uefi \
  --noautoconsole

echo ""
echo "=========================================="
echo "虚拟机已创建！"
echo "=========================================="
echo ""
echo "下一步操作："
echo ""
echo "1. 在你的本地电脑执行 SSH 隧道命令："
echo "   ssh -L 5901:127.0.0.1:5901 root@159.69.60.143"
echo ""
echo "2. 打开 VNC 客户端连接："
echo "   127.0.0.1:5901"
echo ""
echo "3. 在 UEFI 菜单选择 Boot Manager → QEMU DVD-ROM"
echo "   然后疯狂按空格键启动安装程序"
echo ""
```

---

## 13. Cursor SSH 远程开发

通过 SSH 跳板连接到 Windows 虚拟机，实现 Cursor 原生远程开发体验。

### 13.1 Windows 开启 OpenSSH Server

在 Windows PowerShell（管理员）中执行：

```powershell
# 安装 OpenSSH Server
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# 启动并设置开机自启
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# 设置 PowerShell 为默认 Shell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force

# 查看 Windows IP 地址
ipconfig | findstr "IPv4"
```

### 13.2 获取 Windows 虚拟机 IP

在 Ubuntu 宿主机执行：

```bash
virsh domifaddr win11
```

当前 Windows VM IP：`192.168.122.193`

### 13.3 配置本地 SSH Config

> ⚠️ **注意**：以下操作在**你自己的电脑**上执行（运行 Cursor 的那台电脑），不是 Ubuntu 服务器，也不是 Windows 虚拟机！

**macOS / Linux：**

```bash
# 在你自己的电脑终端执行
nano ~/.ssh/config
```

**Windows：**

```powershell
# 在你自己的电脑 PowerShell 执行
notepad C:\Users\$env:USERNAME\.ssh\config
```

如果 `.ssh` 目录不存在，先创建：
```bash
mkdir -p ~/.ssh
```

**添加以下内容：**

```
# Ubuntu 服务器（宿主机）
Host ubuntu-server
    HostName 159.69.60.143
    User root

# Windows 虚拟机（通过 Ubuntu 跳板连接）
Host windows-vm
    HostName 192.168.122.193
    User coin
    ProxyJump ubuntu-server
```

**保存后，连接流程：**

```
你的电脑 ──ssh ubuntu-server──► Ubuntu 服务器
你的电脑 ──ssh windows-vm────► Ubuntu 服务器 ──► Windows 虚拟机（自动跳转）
```

### 13.4 测试连接

```bash
# 测试 SSH 连接（用 PowerShell 语法）
ssh windows-vm "hostname; whoami"
```

预期输出：
```
DESKTOP-EBBSEDJ
desktop-ebbsedj\coin
```

### 13.5 Cursor 连接

1. 打开 Cursor
2. 按 `Ctrl+Shift+P`（Mac: `Cmd+Shift+P`）
3. 输入 `Remote-SSH: Connect to Host`
4. 选择 `windows-vm`
5. 等待连接完成，即可在 Cursor 中开发 Windows 上的代码

### 13.6 SSH 免密登录配置（已完成）

> ✅ Ubuntu 服务器到 Windows 虚拟机的免密登录已配置完成。

**配置原理：**

由于 `coin` 是管理员用户，Windows OpenSSH 要求公钥存放在特殊位置：

```
C:\ProgramData\ssh\administrators_authorized_keys
```

**如需添加其他公钥，在 Windows PowerShell（管理员）执行：**

```powershell
# 添加新公钥到管理员授权文件
$pubKey = "你的公钥内容"
Add-Content -Path "C:\ProgramData\ssh\administrators_authorized_keys" -Value $pubKey

# 设置正确权限
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /grant "Administrators:(R)"
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /grant "SYSTEM:(R)"

# 重启 SSH 服务
Restart-Service sshd
```

**Ubuntu 服务器的 SSH Config（已配置）：**

```bash
# 位置：~/.ssh/config
Host windows-vm
    HostName 192.168.122.193
    User coin
```

### 13.7 网络拓扑

```
你的电脑                    Ubuntu 服务器              Windows 虚拟机
┌──────────┐              ┌──────────────┐           ┌─────────────┐
│ Cursor   │ ──SSH──────► │ 159.69.60.143│ ──SSH───► │192.168.122. │
│          │   (跳板)     │              │  (内网)   │    193      │
└──────────┘              └──────────────┘           └─────────────┘
```

---

## 完成后的使用流程

1. **日常远控**：直接用 RustDesk 连接（使用你记录的 ID + 密码）
2. **紧急情况**：SSH 隧道 + VNC（当 RustDesk 无法连接时）
3. **远程开发**：Cursor SSH 连接 `windows-vm`
4. **维护操作**：通过 virsh 命令管理虚拟机生命周期

---

## 当前部署状态

| 项目 | 状态 |
|------|------|
| 虚拟机名称 | `win11` |
| Windows 主机名 | `DESKTOP-EBBSEDJ` |
| 系统 | Windows 11 Business 23H2 |
| 内存 | 8GB |
| CPU | 4 核 |
| 磁盘 | 80GB |
| 显卡 | QXL (64MB 显存) |
| Windows 用户 | `coin` |
| Windows VM IP | `192.168.122.193` |
| VNC 端口 | 127.0.0.1:5901 |
| SSH 连接 | ✅ `ssh windows-vm`（免密已配置） |
| 状态 | ✅ 运行中 |
