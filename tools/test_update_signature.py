# -*- coding: utf-8 -*-
"""Regression: manifest phát hành phải có chữ ký Ed25519 hợp lệ mới được cập nhật."""
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.update_manifest import canonical_manifest_payload, verify_manifest_signature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tools.sign_release_manifest import ROOT, sign_manifest

SHA = "a" * 64
URL = "https://github.com/example/releases/download/v9/CoNgu_v9_Portable.zip"


class UpdateSignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-update-sign-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private_key = Ed25519PrivateKey.generate()
        self.key_path = self.root / "ed25519_private.pem"
        self.key_path.write_bytes(self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        self.public_pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.manifest = {
            "version": "9.9.9",
            "portable_zip_url": URL,
            "portable_zip_sha256": SHA,
        }

    def signed(self, manifest=None):
        data = dict(manifest or self.manifest)
        signature = self.private_key.sign(canonical_manifest_payload(data))
        data["manifest_signature"] = base64.b64encode(signature).decode("ascii")
        return data

    def verify(self, manifest):
        return verify_manifest_signature(manifest, public_key_pem=self.public_pem)

    def test_valid_signature_verifies(self):
        ok, reason = self.verify(self.signed())
        self.assertTrue(ok, reason)

    def test_tampered_checksum_is_rejected(self):
        manifest = self.signed()
        manifest["portable_zip_sha256"] = "b" * 64
        ok, reason = self.verify(manifest)
        self.assertFalse(ok)
        self.assertIn("không hợp lệ", reason)

    def test_tampered_version_is_rejected(self):
        manifest = self.signed()
        manifest["version"] = "9.9.10"
        self.assertFalse(self.verify(manifest)[0])

    def test_tampered_url_is_rejected(self):
        manifest = self.signed()
        manifest["portable_zip_url"] = URL.replace("example", "evil")
        self.assertFalse(self.verify(manifest)[0])

    def test_missing_signature_is_rejected(self):
        ok, reason = self.verify(dict(self.manifest))
        self.assertFalse(ok)
        self.assertIn("thiếu chữ ký", reason)

    def test_malformed_signature_is_rejected(self):
        manifest = dict(self.manifest, manifest_signature="not-base64!!")
        self.assertFalse(self.verify(manifest)[0])

    def test_sign_tool_writes_verifiable_signature(self):
        manifest_path = self.root / "version.json"
        original = dict(self.manifest, name="Cổ Ngữ", changelog=["x"])
        manifest_path.write_text(json.dumps(original), encoding="utf-8")

        signature = sign_manifest(str(manifest_path), str(self.key_path))

        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(written["manifest_signature"], signature)
        self.assertEqual(written["name"], "Cổ Ngữ")
        self.assertTrue(self.verify(written)[0])

    def test_sign_tool_refuses_key_inside_repository(self):
        manifest_path = self.root / "version.json"
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(SystemExit):
            sign_manifest(str(manifest_path), str(ROOT / "tools" / "release-key.pem"))

    def test_sign_tool_rejects_missing_checksum(self):
        manifest_path = self.root / "version.json"
        manifest_path.write_text(json.dumps(dict(self.manifest, portable_zip_sha256="")), encoding="utf-8")
        with self.assertRaises(SystemExit):
            sign_manifest(str(manifest_path), str(self.key_path))


if __name__ == "__main__":
    unittest.main()
