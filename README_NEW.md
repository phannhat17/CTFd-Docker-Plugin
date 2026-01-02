# Container Challenges Plugin for CTFd (v2.0)

**Redesigned Architecture** - Server-side Docker management với anti-cheat system

## Tính năng

- ✅ Spawn Docker containers cho mỗi team/user
- ✅ Random hoặc static flags  
- ✅ Auto-expiration và renewal
- ✅ Anti-cheat: Flag reuse detection
- ✅ Resource limits (CPU, memory, PIDs)
- ✅ Port management tự động
- ✅ Audit logging đầy đủ
- ✅ Dynamic scoring
- ✅ Docker qua Unix socket hoặc TCP

## Kiến trúc

```
CTFd Server
  ├─ Models (Database)
  │   ├─ ContainerChallenge
  │   ├─ ContainerInstance  
  │   ├─ ContainerFlag
  │   ├─ ContainerFlagAttempt
  │   └─ ContainerAuditLog
  │
  ├─ Services (Business Logic)
  │   ├─ DockerService (Docker daemon interaction)
  │   ├─ FlagService (Flag generation & encryption)
  │   ├─ ContainerService (Container lifecycle)
  │   ├─ AntiCheatService (Flag validation)
  │   └─ PortManager (Port allocation)
  │
  └─ Routes (API)
      ├─ User APIs (/api/v1/containers/*)
      └─ Admin APIs (/admin/containers/*)
```

## Cài đặt

### 1. Dependencies

```bash
cd CTFd/plugins/containers
pip install -r requirements.txt
```

### 2. Docker Setup

Plugin cần access tới Docker daemon. Có 2 cách:

**Option A: Unix Socket (Recommended - cùng host)**
```bash
# CTFd process cần quyền access Docker socket
sudo usermod -aG docker <ctfd_user>

# Hoặc mount socket vào Docker container của CTFd
docker run -v /var/run/docker.sock:/var/run/docker.sock ...
```

**Option B: TCP (Remote Docker host)**
```bash
# Trên Docker host, expose TCP
# /etc/docker/daemon.json:
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
  "tls": true,
  "tlsverify": true
}

# Cấu hình trong plugin settings:
docker_socket = tcp://192.168.1.100:2376
```

### 3. Database Migration

```bash
# Tạo tables
flask db upgrade
# Hoặc
python -c "from CTFd import create_app; app = create_app(); app.db.create_all()"
```

### 4. Configuration

Vào **Admin → Containers → Settings**:

- `docker_socket`: `unix://var/run/docker.sock` hoặc `tcp://...`
- `connection_host`: Host mà users connect tới (IP public của server)
- `port_range_start`: Port bắt đầu (default: 30000)
- `port_range_end`: Port kết thúc (default: 31000)

## Sử dụng

### Tạo Container Challenge

1. Admin → Challenges → Create Challenge
2. Type: **Container**
3. Cấu hình:
   - **Image**: Docker image name (ví dụ: `ubuntu:22.04`)
   - **Internal Port**: Port bên trong container (ví dụ: 22 cho SSH)
   - **Connection Type**: ssh/http/nc/custom
   - **Timeout**: Số phút trước khi container expire (default: 60)
   - **Max Renewals**: Số lần user có thể renew (default: 3)
   - **Flag Mode**: 
     - `random`: Mỗi container có flag riêng
     - `static`: Tất cả containers dùng chung flag

### User Workflow

1. Click "Start Container" trên challenge
2. Server:
   - Generate flag
   - Tạo Docker container
   - Allocate port
   - Return connection info
3. User connect tới container (SSH/HTTP/etc)
4. User tìm flag trong container
5. Submit flag → Server validate
6. Nếu đúng → Container stopped, solve recorded

### Anti-Cheat Logic

Khi user submit flag:

1. Hash submitted flag
2. Query database tìm flag
3. **Nếu flag không tồn tại**: Incorrect
4. **Nếu flag thuộc account khác**: 
   - Log cheat attempt (severity: critical)
   - Return "Incorrect" (không tiết lộ phát hiện)
   - Admin có thể xem trong Cheats dashboard
5. **Nếu flag thuộc account này**: Correct!

## API Endpoints

### User APIs

```
POST /api/v1/containers/request
Body: {"challenge_id": 123}
→ Tạo hoặc lấy existing container

GET /api/v1/containers/info/<challenge_id>
→ Get container info

POST /api/v1/containers/renew
Body: {"challenge_id": 123}
→ Extend expiration time

POST /api/v1/containers/stop
Body: {"challenge_id": 123}
→ Stop container manually
```

### Admin APIs

```
GET /admin/containers/api/instances
→ List all instances

POST /admin/containers/api/instances/<id>/stop
→ Stop specific instance

GET /admin/containers/api/stats
→ Statistics

GET /admin/containers/api/cheats
→ Cheat attempts

POST /admin/containers/api/config
→ Update config
```

## Database Schema

### container_instances
- `uuid`: Unique identifier
- `challenge_id`: Reference to challenge
- `account_id`: Team ID hoặc User ID
- `container_id`: Docker container ID
- `connection_host`, `connection_port`: Connection info
- `flag_encrypted`: Encrypted flag
- `flag_hash`: SHA256 hash (for validation)
- `status`: pending/provisioning/running/stopped/solved/error
- `expires_at`: Expiration time
- `renewal_count`: Số lần đã renew

### container_flags
- `flag_hash`: Unique hash of flag
- `instance_id`: Reference to instance
- `account_id`: Owner
- `flag_status`: temporary/submitted_correct/invalidated
- `submitted_at`, `submitted_by_user_id`: Submission info

### container_flag_attempts
- Log mọi flag submission attempts
- Track cheating: `is_cheating`, `flag_owner_account_id`

### container_audit_logs
- Comprehensive audit trail
- Events: instance_created, flag_reuse_detected, etc.
- Severity: info/warning/error/critical

## Background Jobs

Plugin tự động chạy cleanup jobs:

- **Every 1 minute**: Cleanup expired containers
- **Every 1 hour**: Delete old stopped instances (>24h)

Sử dụng APScheduler. Nếu cần production-grade, migrate sang Celery.

## Troubleshooting

### Docker connection failed

```bash
# Check Docker is running
sudo systemctl status docker

# Check socket permissions
ls -la /var/run/docker.sock

# Test connection
docker ps
```

### No available ports

- Tăng port range trong settings
- Check firewall rules
- Cleanup old containers

### Container fails to start

- Check image exists: `docker images`
- Check logs: Admin → Instances → Logs
- Check resource limits

## Security Considerations

- ✅ Flags được encrypt trong database (Fernet)
- ✅ Docker containers chạy với minimal capabilities
- ✅ Resource limits để prevent DoS
- ✅ Port isolation (containers không thể access nhau)
- ⚠️ Nên dùng TLS cho Docker TCP connection
- ⚠️ Nên có firewall rules cho port range

## Development

```bash
# Structure
CTFd/plugins/containers/
├── models/          # Database models
├── services/        # Business logic
├── routes/          # API endpoints
├── utils/           # Utilities
├── templates/       # HTML templates
├── assets/          # JS/CSS
└── __init__.py      # Plugin entry point
```

## License

MIT License - See LICENSE file

## Credits

Redesigned from [CTFd-Docker-Plugin](https://github.com/phannhat17/CTFd-Docker-Plugin)

