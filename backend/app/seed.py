"""开发环境种子数据：首次启动时写入默认账号与演示项目。

与前端 src/context/AuthContext.tsx 的 defaultUser、src/mocks/projects.ts 的
projects 数组保持一致，确保迁移到真实后端后功能演示不受影响
（projects/page.tsx 里按 p-1001~p-1007 硬编码的 defaultAssignments 依然生效）。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Project, User

DEFAULT_USER = {
    "id": "user-000000000001",
    "name": "陈立群",
    "email": "chen@zhibiaoyun.com",
    "password": "123456",
    "phone": "138 0013 8000",
    "company": "中建八局·华东公司",
    "position": "投标主管",
    "role": "管理员",
}

SEED_PROJECTS = [
    {
        "id": "p-1001",
        "code": "ZB-2026-0412",
        "name": "城市轨道交通 3 号线智能化机电安装工程",
        "type": "交通",
        "owner": "陈立群",
        "budget": "¥ 8,600 万",
        "deadline": "2026-08-28",
        "progress": 76,
        "score": 91.5,
        "status": "评标中",
        "created_at": "2026-06-18",
    },
    {
        "id": "p-1002",
        "code": "CG-2026-0877",
        "name": "市政务数据中心云资源池扩容采购项目",
        "type": "政采",
        "owner": "林晓雯",
        "budget": "¥ 2,450 万",
        "deadline": "2026-08-22",
        "progress": 92,
        "score": 88.2,
        "status": "已提交",
        "created_at": "2026-06-25",
    },
    {
        "id": "p-1003",
        "code": "GX-2026-1530",
        "name": "三甲医院智慧医疗一体化信息平台建设",
        "type": "医疗",
        "owner": "王浩然",
        "budget": "¥ 3,180 万",
        "deadline": "2026-09-05",
        "progress": 45,
        "score": 84.6,
        "status": "撰写中",
        "created_at": "2026-07-02",
    },
    {
        "id": "p-1004",
        "code": "YT-2026-0934",
        "name": "河西综合管廊二期土建施工总承包工程",
        "type": "工程",
        "owner": "赵启铭",
        "budget": "¥ 12,900 万",
        "deadline": "2026-08-15",
        "progress": 100,
        "score": 93.1,
        "status": "已中标",
        "created_at": "2026-05-20",
    },
    {
        "id": "p-1005",
        "code": "XX-2026-0219",
        "name": "省级国资云安全态势感知平台建设项目",
        "type": "IT",
        "owner": "李思源",
        "budget": "¥ 1,860 万",
        "deadline": "2026-09-12",
        "progress": 18,
        "score": 0,
        "status": "撰写中",
        "created_at": "2026-07-20",
    },
    {
        "id": "p-1006",
        "code": "NY-2026-0671",
        "name": "光伏电站智能运维监控系统集成项目",
        "type": "能源",
        "owner": "陈立群",
        "budget": "¥ 4,520 万",
        "deadline": "2026-08-30",
        "progress": 100,
        "score": 79.8,
        "status": "未中标",
        "created_at": "2026-04-15",
    },
    {
        "id": "p-1007",
        "code": "CG-2026-1022",
        "name": "智慧园区一网统管综合服务平台建设",
        "type": "政采",
        "owner": "林晓雯",
        "budget": "¥ 2,980 万",
        "deadline": "2026-09-20",
        "progress": 8,
        "score": 0,
        "status": "撰写中",
        "created_at": "2026-08-02",
    },
]


def seed_defaults(db: Session) -> None:
    default_user = None
    if db.query(User).count() == 0:
        default_user = User(
            id=DEFAULT_USER["id"],
            name=DEFAULT_USER["name"],
            email=DEFAULT_USER["email"],
            password_hash=hash_password(DEFAULT_USER["password"]),
            phone=DEFAULT_USER["phone"],
            company=DEFAULT_USER["company"],
            position=DEFAULT_USER["position"],
            role=DEFAULT_USER["role"],
        )
        db.add(default_user)
        db.flush()

    if db.query(Project).count() == 0:
        owner_id = default_user.id if default_user else None
        for item in SEED_PROJECTS:
            db.add(
                Project(
                    id=item["id"],
                    code=item["code"],
                    name=item["name"],
                    type=item["type"],
                    owner=item["owner"],
                    owner_id=owner_id,
                    budget=item["budget"],
                    deadline=item["deadline"],
                    progress=item["progress"],
                    score=item["score"],
                    status=item["status"],
                    created_at=datetime.strptime(item["created_at"], "%Y-%m-%d"),
                )
            )

    db.commit()
