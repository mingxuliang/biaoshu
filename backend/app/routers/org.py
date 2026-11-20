"""企业组织：企业资料与认证、部门树、自定义角色、运维授权、平台公告。

部门和角色表都在本企业 schema 内，接口不可能返回别家企业的组织架构。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import storage
from ..audit import write_audit
from ..auth import get_current_user
from ..db import assert_tenant_session, get_db, get_platform_db
from ..models import CustomRole, Department, User
from ..tenants import KIND_PERSONAL, tenant_kind, upgrade_to_enterprise
from ..permissions import (
    ALL_PERMS,
    PERM_BILLING,
    PERM_EXPORT,
    PERM_MEMBERS,
    PERM_ORG,
    PERM_PROJECT_EDIT,
    PERM_QUAL_EDIT,
    PERM_REVIEW,
    PERM_SETTINGS,
    PERM_WRITER,
    SCOPE_ALL,
    SCOPE_DEPT,
    SCOPE_SELF,
    is_admin,
    require_perm,
)

router = APIRouter(prefix="/api/org", tags=["org"])

PERM_LABELS = {
    PERM_PROJECT_EDIT: "新建和编辑项目",
    PERM_WRITER: "标书撰写",
    PERM_EXPORT: "导出标书",
    PERM_MEMBERS: "成员管理",
    PERM_SETTINGS: "规则与系统设置",
    PERM_QUAL_EDIT: "维护资质和产品库",
    PERM_REVIEW: "预审评审",
    PERM_BILLING: "充值、套餐与发票",
    PERM_ORG: "部门、角色与企业资料",
}
SCOPES = (SCOPE_SELF, SCOPE_DEPT, SCOPE_ALL)
LICENSE_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


# ---------------------------------------------------------------------------
# 企业资料与认证
# ---------------------------------------------------------------------------


def _tenant_out(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "kind": tenant_kind(t),
        "status": t.status,
        "planCode": t.plan_code,
        "seats": t.seats,
        "storageQuotaMb": t.storage_quota_mb,
        "features": t.features_json or {},
        "verifyStatus": t.verify_status,
        "verifyNote": t.verify_note or "",
        "licenseNo": t.license_no or "",
        "hasLicense": bool(t.license_key),
        "contactName": t.contact_name or "",
        "contactPhone": t.contact_phone or "",
        "contactEmail": t.contact_email or "",
        "trialEndsAt": _dt(t.trial_ends_at),
        "expiresAt": _dt(t.expires_at),
        "lowBalanceThreshold": t.low_balance_threshold or 0,
        "createdAt": _dt(t.created_at),
    }


def _my_tenant(db: Session, pdb: Session):
    from ..platform_models import Tenant

    tenant = pdb.get(Tenant, assert_tenant_session(db))
    if tenant is None:
        raise HTTPException(404, "企业不存在")
    return tenant


@router.get("/tenant")
def get_tenant(db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    return _tenant_out(_my_tenant(db, pdb))


class TenantProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contactName: str = Field("", max_length=60)
    contactPhone: str = Field("", max_length=40)
    contactEmail: str = Field("", max_length=120)
    lowBalanceThreshold: int = Field(200, ge=0, le=10_000_000)


@router.put("/tenant")
def update_tenant(
    payload: TenantProfileIn,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_ORG)
    tenant = _my_tenant(db, pdb)
    # 已认证企业的名称以营业执照为准，改名需重新认证
    if tenant.verify_status == "已认证" and payload.name.strip() != tenant.name:
        tenant.verify_status = "未认证"
        tenant.verify_note = "企业名称已修改，请重新认证"
    tenant.name = payload.name.strip()
    tenant.contact_name = payload.contactName.strip()
    tenant.contact_phone = payload.contactPhone.strip()
    tenant.contact_email = payload.contactEmail.strip()
    tenant.low_balance_threshold = payload.lowBalanceThreshold
    pdb.commit()
    write_audit(db, action="修改企业资料", user_name=current_user.name, target=tenant.name, detail="")
    db.commit()
    return _tenant_out(tenant)


class UpgradeIn(BaseModel):
    companyName: str = Field(min_length=2, max_length=120)


@router.post("/tenant/upgrade")
def upgrade_tenant(
    payload: UpgradeIn,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """个人空间升级为企业：本人成为企业管理员，项目、资料库、积分和套餐都保留。"""
    require_perm(current_user, PERM_ORG)
    tenant = _my_tenant(db, pdb)
    upgrade_to_enterprise(pdb, tenant, payload.companyName)
    pdb.commit()
    current_user.company = tenant.name
    if (current_user.position or "") in ("", "本人"):
        current_user.position = "企业管理员"
    write_audit(db, action="升级为企业", user_name=current_user.name, target=tenant.name, detail="")
    db.commit()
    return _tenant_out(tenant)


@router.post("/tenant/verify")
async def submit_verify(
    licenseNo: str = Form(..., min_length=15, max_length=20),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """提交营业执照做企业认证。执照存本企业 bucket，平台审核时临时读取。"""
    require_perm(current_user, PERM_ORG)
    tenant = _my_tenant(db, pdb)
    if tenant_kind(tenant) == KIND_PERSONAL:
        raise HTTPException(400, "个人账号无需企业认证，升级为企业后再提交营业执照")
    if tenant.verify_status == "待审核":
        raise HTTPException(400, "认证资料审核中，请耐心等待")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in LICENSE_EXTS:
        raise HTTPException(400, "营业执照仅支持 PDF 或图片")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "营业执照文件不能超过 10 MB")
    old = tenant.license_key
    tenant.license_key = storage.put_bytes("org/license", data, ext)
    tenant.license_no = licenseNo.strip().upper()
    tenant.verify_status = "待审核"
    tenant.verify_note = ""
    pdb.commit()
    if old and old != tenant.license_key:
        storage.delete(old)
    return _tenant_out(tenant)


@router.get("/tenant/license")
def get_license(db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)):
    require_perm(current_user, PERM_ORG)
    tenant = _my_tenant(db, pdb)
    if not tenant.license_key:
        raise HTTPException(404, "未上传营业执照")
    return storage.http_response(tenant.license_key, inline=True)


# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parentId: str | None = None
    leaderId: str | None = None
    sortOrder: int = 0


def _dept_out(d: Department, counts: dict[str, int], names: dict[str, str]) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "parentId": d.parent_id,
        "leaderId": d.leader_id,
        "leaderName": names.get(d.leader_id or "", ""),
        "sortOrder": d.sort_order or 0,
        "memberCount": counts.get(d.id, 0),
    }


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    rows = db.query(Department).order_by(Department.sort_order.asc(), Department.created_at.asc()).all()
    counts = dict(
        db.query(User.department_id, func.count(User.id))
        .filter(User.department_id.isnot(None), User.disabled.is_(False))
        .group_by(User.department_id)
        .all()
    )
    names = dict(db.query(User.id, User.name).all())
    return [_dept_out(d, counts, names) for d in rows]


def _check_parent(db: Session, dept_id: str | None, parent_id: str | None) -> None:
    if not parent_id:
        return
    seen = set()
    cursor = db.get(Department, parent_id)
    if cursor is None:
        raise HTTPException(400, "上级部门不存在")
    while cursor is not None:
        if cursor.id == dept_id or cursor.id in seen:
            raise HTTPException(400, "不能把部门移到自己的下级部门下")
        seen.add(cursor.id)
        if len(seen) > 20:
            raise HTTPException(400, "部门层级不能超过 20 级")
        cursor = db.get(Department, cursor.parent_id) if cursor.parent_id else None


def _check_leader(db: Session, leader_id: str | None) -> None:
    if leader_id and db.get(User, leader_id) is None:
        raise HTTPException(400, "负责人不存在")


@router.post("/departments")
def create_department(payload: DepartmentIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    _check_parent(db, None, payload.parentId)
    _check_leader(db, payload.leaderId)
    dept = Department(name=payload.name.strip(), parent_id=payload.parentId or None, leader_id=payload.leaderId or None, sort_order=payload.sortOrder)
    db.add(dept)
    write_audit(db, action="新建部门", user_name=current_user.name, target=dept.name, detail="")
    db.commit()
    return _dept_out(dept, {}, {})


@router.put("/departments/{dept_id}")
def update_department(dept_id: str, payload: DepartmentIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(404, "部门不存在")
    _check_parent(db, dept_id, payload.parentId)
    _check_leader(db, payload.leaderId)
    dept.name = payload.name.strip()
    dept.parent_id = payload.parentId or None
    dept.leader_id = payload.leaderId or None
    dept.sort_order = payload.sortOrder
    write_audit(db, action="修改部门", user_name=current_user.name, target=dept.name, detail="")
    db.commit()
    return _dept_out(dept, {}, {})


@router.delete("/departments/{dept_id}")
def delete_department(dept_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(404, "部门不存在")
    if db.query(Department).filter(Department.parent_id == dept_id).count():
        raise HTTPException(400, "请先删除或移走下级部门")
    if db.query(User).filter(User.department_id == dept_id).count():
        raise HTTPException(400, "部门下还有成员，请先调整成员部门")
    from ..models import KnowledgeDocument

    if db.query(KnowledgeDocument).filter(KnowledgeDocument.scope == "部门库", KnowledgeDocument.department_id == dept_id).count():
        raise HTTPException(400, "部门库里还有文档，请先移走或删除")
    db.delete(dept)
    write_audit(db, action="删除部门", user_name=current_user.name, target=dept.name, detail="")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 自定义角色
# ---------------------------------------------------------------------------


class CustomRoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    perms: list[str] = Field(default_factory=list)
    dataScope: str = SCOPE_SELF


def _role_out(r: CustomRole, counts: dict[str, int]) -> dict:
    return {"id": r.id, "name": r.name, "perms": list(r.perms_json or []), "dataScope": r.data_scope, "memberCount": counts.get(r.id, 0)}


@router.get("/perm-catalog")
def perm_catalog(current_user: User = Depends(get_current_user)) -> dict:
    return {"perms": [{"id": p, "name": PERM_LABELS.get(p, p)} for p in ALL_PERMS], "scopes": list(SCOPES)}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    counts = dict(
        db.query(User.custom_role_id, func.count(User.id)).filter(User.custom_role_id.isnot(None)).group_by(User.custom_role_id).all()
    )
    return [_role_out(r, counts) for r in db.query(CustomRole).order_by(CustomRole.created_at.asc()).all()]


def _validate_role(db: Session, payload: CustomRoleIn, role_id: str | None) -> None:
    bad = [p for p in payload.perms if p not in ALL_PERMS]
    if bad:
        raise HTTPException(400, f"未知权限：{', '.join(bad)}")
    if payload.dataScope not in SCOPES:
        raise HTTPException(400, "数据范围不合法")
    dup = db.query(CustomRole).filter(CustomRole.name == payload.name.strip())
    if role_id:
        dup = dup.filter(CustomRole.id != role_id)
    if dup.first():
        raise HTTPException(409, "角色名称已存在")


@router.post("/roles")
def create_role(payload: CustomRoleIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    _validate_role(db, payload, None)
    role = CustomRole(name=payload.name.strip(), perms_json=sorted(set(payload.perms)), data_scope=payload.dataScope)
    db.add(role)
    write_audit(db, action="新建角色", user_name=current_user.name, target=role.name, detail=",".join(role.perms_json))
    db.commit()
    return _role_out(role, {})


@router.put("/roles/{role_id}")
def update_role(role_id: str, payload: CustomRoleIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    role = db.get(CustomRole, role_id)
    if role is None:
        raise HTTPException(404, "角色不存在")
    _validate_role(db, payload, role_id)
    role.name = payload.name.strip()
    role.perms_json = sorted(set(payload.perms))
    role.data_scope = payload.dataScope
    write_audit(db, action="修改角色", user_name=current_user.name, target=role.name, detail=",".join(role.perms_json))
    db.commit()
    return _role_out(role, {})


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    require_perm(current_user, PERM_ORG)
    role = db.get(CustomRole, role_id)
    if role is None:
        raise HTTPException(404, "角色不存在")
    if db.query(User).filter(User.custom_role_id == role_id).count():
        raise HTTPException(400, "还有成员使用该角色，请先调整")
    db.delete(role)
    write_audit(db, action="删除角色", user_name=current_user.name, target=role.name, detail="")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 运维授权：企业管理员授权后，平台运维才能在限定时间内查看本企业的文件内容排查问题
# ---------------------------------------------------------------------------


class SupportGrantIn(BaseModel):
    hours: int = Field(24, ge=1, le=168)
    reason: str = Field("", max_length=200)


def _grant_out(g) -> dict:
    return {
        "id": g.id,
        "grantedBy": g.granted_by,
        "reason": g.reason,
        "expiresAt": _dt(g.expires_at),
        "active": (not g.revoked) and g.expires_at > datetime.utcnow(),
        "revoked": bool(g.revoked),
        "createdAt": _dt(g.created_at),
    }


@router.get("/support-grants")
def list_grants(db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from ..platform_models import SupportGrant

    if not is_admin(current_user):
        raise HTTPException(403, "仅企业管理员可管理运维授权")
    tid = assert_tenant_session(db)
    rows = pdb.query(SupportGrant).filter(SupportGrant.tenant_id == tid).order_by(SupportGrant.created_at.desc()).limit(50).all()
    return [_grant_out(g) for g in rows]


@router.post("/support-grants")
def create_grant(payload: SupportGrantIn, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import SupportGrant

    if not is_admin(current_user):
        raise HTTPException(403, "仅企业管理员可管理运维授权")
    tid = assert_tenant_session(db)
    grant = SupportGrant(
        tenant_id=tid,
        granted_by=current_user.name or current_user.email,
        reason=payload.reason.strip(),
        expires_at=datetime.utcnow() + timedelta(hours=payload.hours),
    )
    pdb.add(grant)
    pdb.commit()
    write_audit(db, action="授权平台运维", user_name=current_user.name, target=f"{payload.hours} 小时", detail=payload.reason)
    db.commit()
    return _grant_out(grant)


@router.delete("/support-grants/{grant_id}")
def revoke_grant(grant_id: str, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import SupportGrant

    if not is_admin(current_user):
        raise HTTPException(403, "仅企业管理员可管理运维授权")
    tid = assert_tenant_session(db)
    grant = pdb.get(SupportGrant, grant_id)
    if grant is None or grant.tenant_id != tid:
        raise HTTPException(404, "授权不存在")
    grant.revoked = True
    pdb.commit()
    write_audit(db, action="撤销运维授权", user_name=current_user.name, target=grant_id, detail="")
    db.commit()
    return _grant_out(grant)


# ---------------------------------------------------------------------------
# 公告
# ---------------------------------------------------------------------------


@router.get("/announcements")
def announcements(pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from ..platform_models import Announcement

    rows = pdb.query(Announcement).filter(Announcement.published.is_(True)).order_by(Announcement.created_at.desc()).limit(10).all()
    return [{"id": a.id, "title": a.title, "body": a.body, "level": a.level, "createdAt": _dt(a.created_at)} for a in rows]
