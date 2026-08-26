"""
SSL 证书信任修复
================
本机存在 SSL 拦截（自签名证书）时，certifi 默认 CA 包不含代理/公司根证书，
导致 akshare / 东财 / 乐咕等所有 HTTPS 请求报
`SSL_CERTIFICATE_VERIFY_FAILED: self signed certificate`。

本模块将 certifi 的 CA + macOS 系统根证书（Keychain）+ 用户额外指定的 CA
合并为统一 bundle，并设置 SSL_CERT_FILE / REQUESTS_CA_BUNDLE 环境变量，
使 requests/urllib3 信任系统根证书，从而打通数据源。

用法：
    from utils.ssl_setup import setup_ssl
    setup_ssl()

若代理根证书不在系统钥匙串中，可额外指定：
    export MEGOO_EXTRA_CA_BUNDLE=/path/to/extra-ca.pem
"""
import os
import sys
import subprocess
from pathlib import Path

from utils.logger import logger

# 合并后的 CA bundle 存放位置（运行时生成，勿手改）
_BUNDLE_PATH = Path(__file__).resolve().parent.parent / "config" / "ca_bundle.pem"

_BEGIN = "-----BEGIN CERTIFICATE-----"
_END = "-----END CERTIFICATE-----"

# 进程内只初始化一次，避免重复生成
_initialized = False


def _cert_blocks(pem_text: str):
    """从 PEM 文本中提取去重后的证书块"""
    blocks = []
    seen = set()
    for chunk in pem_text.split(_BEGIN):
        chunk = chunk.strip()
        if not chunk or _END not in chunk:
            continue
        body = chunk.split(_END)[0].strip()
        if body in seen:
            continue
        seen.add(body)
        blocks.append(_BEGIN + "\n" + chunk + "\n")
    return blocks


def _read_pem(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _macos_system_certs() -> str:
    """导出 macOS 系统根证书（含公司/代理根证书）"""
    keychains = [
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        "/Library/Keychains/System.keychain",
    ]
    out = []
    for kc in keychains:
        if not os.path.exists(kc):
            continue
        try:
            r = subprocess.run(
                ["security", "find-certificate", "-a", "-p", kc],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode == 0 and r.stdout.strip():
                out.append(r.stdout)
        except Exception as e:
            logger.debug(f"导出系统证书失败 {kc}: {e}")
    return "\n".join(out)


def setup_ssl() -> str:
    """合并 CA 并设置环境变量，返回 bundle 路径（幂等）"""
    global _initialized
    if _initialized:
        return str(_BUNDLE_PATH)

    import certifi

    parts = [certifi.where()]
    extra = os.environ.get("MEGOO_EXTRA_CA_BUNDLE", "")
    if extra:
        parts.append(extra)

    pem_text = "\n".join(_read_pem(p) for p in parts)

    # macOS 系统根证书（覆盖公司/代理自签证书）
    if sys.platform == "darwin":
        sys_certs = _macos_system_certs()
        if sys_certs:
            pem_text += "\n" + sys_certs

    blocks = _cert_blocks(pem_text)
    if not blocks:
        # 兜底：至少保留 certifi 原始内容
        blocks = _cert_blocks(_read_pem(certifi.where()))

    merged = "".join(blocks)
    try:
        _BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BUNDLE_PATH.write_text(merged, encoding="utf-8")
    except Exception as e:
        logger.warning(f"写入合并 CA bundle 失败，回退 certifi: {e}")
        merged = _read_pem(certifi.where())

    os.environ["SSL_CERT_FILE"] = str(_BUNDLE_PATH)
    os.environ["REQUESTS_CA_BUNDLE"] = str(_BUNDLE_PATH)
    logger.info(f"🔐 SSL CA bundle 已就绪（含系统根证书，共 {len(blocks)} 个）：{_BUNDLE_PATH}")

    _initialized = True
    return str(_BUNDLE_PATH)
