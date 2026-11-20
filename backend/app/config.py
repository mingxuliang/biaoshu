from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置，容器内由 docker-compose 的 env_file 注入；本地直接运行时回退读取 .env。"""

    database_url: str = "postgresql+psycopg2://prereview:prereview@localhost:5434/prereview"
    redis_url: str = "redis://localhost:6380/0"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_image_model: str = "doubao-seedream-4-0-250828"
    ark_chat_model: str = "doubao-seed-1-8-251228"

    upload_dir: str = "./uploads"
    sample_dir: str = "./sample_data"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "zhibiaoyun"
    minio_secure: bool = False

    cors_origins: str = "http://localhost:3000"

    writer_browser_url: str = ""
    writer_browser_timeout_sec: int = 25
    writer_browser_hosts: str = (
        "gov.cn,ccgp.gov.cn,ggzy.gov.cn,chinabidding.com,"
        "bidcenter.com.cn,duckduckgo.com,bing.com"
    )

    # 与 writer-browser 服务约定的共享口令，两边必须一致
    writer_browser_token: str = ""

    # MinerU HTTP 服务（mineru-api），留空则扫描件只走 Tesseract
    mineru_url: str = ""
    mineru_timeout_sec: int = 180
    mineru_backend: str = "pipeline"

    # 版式预览用的常驻 LibreOffice 服务（backend/lo）；不可达时回退本机 soffice，再不行预览返回 503
    lo_render_url: str = "http://lo:8090"
    lo_render_timeout_sec: int = 100

    # dev / prod；prod 下默认密钥拒绝启动并关闭接口文档
    app_env: str = "dev"
    allow_register: bool = False
    admin_initial_password: str = ""
    # 允许 LLM base_url 指向内网地址（自建模型网关时开启）
    llm_allow_private_base_url: bool = False
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24

    # 单次请求体上限（MB），多文件上传按总大小计
    max_upload_mb: int = 500

    # ---- SaaS ----
    # 非默认企业的 bucket 名为 {前缀}-{企业ID}
    minio_bucket_prefix: str = "zby"
    # 企业自助开通：开启后登录页出现「企业注册」
    allow_tenant_signup: bool = True
    trial_credits: int = 2000
    trial_days: int = 14
    # 短信/邮件验证码通道：mock 时验证码写日志，便于联调
    verify_code_channel: str = "mock"
    # 平台管理后台初始账号
    platform_admin_email: str = "admin@platform.local"
    platform_admin_password: str = ""
    platform_token_expire_minutes: int = 60 * 8
    # 逗号分隔的 IP，留空不限制
    platform_admin_ip_allowlist: str = ""

    # 公网回调地址前缀，如 https://bid.example.com ，用于支付异步通知
    public_base_url: str = "http://localhost:8000"
    pay_order_expire_minutes: int = 30
    # 1 元兑换的积分
    credits_per_yuan: int = 10

    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_public_key: str = ""
    alipay_gateway: str = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"

    wechat_mchid: str = ""
    wechat_appid: str = ""
    wechat_serial_no: str = ""
    wechat_private_key: str = ""
    wechat_api_v3_key: str = ""
    # 微信支付平台公钥（或平台证书公钥）PEM，用于回调验签
    wechat_platform_public_key: str = ""
    wechat_platform_serial: str = ""
    wechat_api_base: str = "https://api.mch.weixin.qq.com"

    # 对公转账收款账户，展示给企业
    bank_account_name: str = ""
    bank_account_no: str = ""
    bank_name: str = ""

    @property
    def is_prod(self) -> bool:
        return (self.app_env or "").strip().lower() in ("prod", "production")

    @property
    def insecure_defaults(self) -> list[str]:
        """仍在使用的开发默认密钥，部署到生产前需要替换。"""
        issues: list[str] = []
        if self.secret_key in ("dev-secret-change-me", "change-me-to-a-random-secret"):
            issues.append("SECRET_KEY 仍是默认值，登录令牌可被伪造")
        if self.minio_secret_key == "minioadmin" or self.minio_access_key == "minioadmin":
            issues.append("MinIO 仍在使用默认账号 minioadmin")
        return issues

    @property
    def mock_payment_enabled(self) -> bool:
        return not self.is_prod

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
