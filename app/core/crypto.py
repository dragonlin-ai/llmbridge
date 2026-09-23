"""厂商 API Key 加解密：AES-256-GCM，密文格式 v1:<nonce_b64>:<ciphertext_b64>。

主密钥从配置注入（ENCRYPTION_MASTER_KEY）。密文带版本前缀，为 V1.1 密钥轮换预留
多密钥灰度空间。明文 Key 永不落库、永不回显、永不入日志。
"""
import base64
import binascii
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_VERSION = b"v1"
_NONCE_LEN = 12


def _derive_key() -> bytes:
    """由主密钥字符串派生 32 字节 AES 密钥（sha256）。"""
    master = get_settings().encryption_master_key
    return hashlib.sha256(master.encode("utf-8")).digest()


def encrypt_api_key(plaintext: str) -> str:
    key = _derive_key()
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=_VERSION)
    return "v1:{}:{}".format(
        base64.urlsafe_b64encode(nonce).decode(),
        base64.urlsafe_b64encode(ct).decode(),
    )


def decrypt_api_key(token: str) -> str:
    """解密失败抛 ValueError（密钥不匹配/密文损坏/格式非法）。

    调用方（adapters/chat 链路）应将其视为上游不可用，走降级而非裸 5xx。
    """
    try:
        version, nonce_b64, ct_b64 = token.split(":")
        if version != "v1":
            raise ValueError("unsupported ciphertext version")
        nonce = base64.urlsafe_b64decode(nonce_b64)
        ct = base64.urlsafe_b64decode(ct_b64)
        key = _derive_key()
        pt = AESGCM(key).decrypt(nonce, ct, associated_data=version.encode())
        return pt.decode("utf-8")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("api key decrypt failed") from e


def mask_api_key(plaintext: str) -> str:
    """掩码回显：sk-****abcd 形态；过短输入统一为 ****。"""
    if len(plaintext) <= 4:
        return "****"
    return plaintext[:3] + "****" + plaintext[-4:]


def mask_token(ciphertext: str, fallback: str = "****") -> str:
    """对密文做一致性掩码（不接触明文时的展示兜底）。"""
    if not ciphertext:
        return fallback
    digest = hashlib.sha256(ciphertext.encode()).hexdigest()[-4:]
    return f"****{digest}"
