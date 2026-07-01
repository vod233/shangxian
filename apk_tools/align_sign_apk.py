"""
Align and sign the customized uiautomator APK.

Android 11+ rejects targetSdk >= 30 APKs when resources.arsc is stored
uncompressed but not aligned on a 4-byte boundary. The required order is:
unsigned APK -> zipalign -> apksigner -> zipalign check.

安全：
- 使用 release.keystore（发布密钥），禁止使用 debug.keystore；
- keystore / key 密码通过环境变量注入（RELEASE_KS_PASS / RELEASE_KEY_PASS），
  不得硬编码到代码中；
- 可选加载 apk_tools/keystore.env（已加入 .gitignore）作为本地开发兜底。
"""
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUILD_TOOLS = Path(os.environ.get("ANDROID_BUILD_TOOLS", r"D:\AndroidSDK\build-tools\33.0.1"))
ZIPALIGN = BUILD_TOOLS / "zipalign.exe"
APKSIGNER = BUILD_TOOLS / "apksigner.bat"
KEYSTORE = ROOT / os.environ.get("RELEASE_KEYSTORE_NAME", "release.keystore")
KEY_ALIAS = os.environ.get("RELEASE_KEY_ALIAS", "qianban-release")
UNSIGNED_APK = ROOT / "app-uiautomator-tech-unsigned.apk"
ALIGNED_APK = ROOT / "app-uiautomator-tech-aligned.apk"
SIGNED_APK = ROOT / "app-uiautomator-tech.apk"

# 可选：从 apk_tools/keystore.env 加载密钥（该文件不应入仓）
_ENV_FILE = ROOT / "keystore.env"
if _ENV_FILE.exists() and not os.environ.get("RELEASE_KS_PASS"):
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())


def _require_env(name: str) -> str:
    """强制要求环境变量，避免硬编码密钥。"""
    val = os.environ.get(name)
    if not val:
        raise SystemExit(
            f"缺少环境变量 {name}。请设置后重试，或将密码写入 apk_tools/keystore.env（已 .gitignore）。"
        )
    return val


def run(cmd):
    print(" ".join(str(part) for part in cmd))
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    for path in (ZIPALIGN, APKSIGNER, KEYSTORE, UNSIGNED_APK):
        if not path.exists():
            raise SystemExit(f"missing required file: {path}")

    ks_pass = _require_env("RELEASE_KS_PASS")
    key_pass = _require_env("RELEASE_KEY_PASS")

    if SIGNED_APK.exists():
        backup = SIGNED_APK.with_suffix(f".apk.bak-align-{os.getpid()}")
        shutil.copy2(SIGNED_APK, backup)
        print(f"backup: {backup}")

    if ALIGNED_APK.exists():
        ALIGNED_APK.unlink()

    run([ZIPALIGN, "-f", "-p", "4", UNSIGNED_APK, ALIGNED_APK])
    run([
        APKSIGNER,
        "sign",
        "--ks", KEYSTORE,
        "--ks-key-alias", KEY_ALIAS,
        "--ks-pass", f"pass:{ks_pass}",
        "--key-pass", f"pass:{key_pass}",
        "--out", SIGNED_APK,
        ALIGNED_APK,
    ])
    run([ZIPALIGN, "-c", "-p", "4", SIGNED_APK])
    run([APKSIGNER, "verify", "--verbose", SIGNED_APK])
    print(f"ready: {SIGNED_APK}")


if __name__ == "__main__":
    main()
