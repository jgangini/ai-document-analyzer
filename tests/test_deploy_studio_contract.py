import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployStudioContractTests(unittest.TestCase):
    def test_contract_points_to_safe_terraform_package(self) -> None:
        contract = json.loads((ROOT / "terraform" / "deploy-studio.json").read_text(encoding="utf-8"))

        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(contract["project_id"], "ai-document-analyzer")
        terraform_path = ROOT / contract["terraform"]["path"]
        self.assertTrue(terraform_path.is_dir())
        self.assertTrue(any(terraform_path.glob("*.tf")))
        self.assertFalse((terraform_path / ".oci").exists())

    def test_declared_outputs_are_not_secrets(self) -> None:
        contract = json.loads((ROOT / "terraform" / "deploy-studio.json").read_text(encoding="utf-8"))
        forbidden = ("password", "private_key", "wallet_base64", "secret")

        self.assertFalse(any(token in name.lower() for name in contract["outputs"] for token in forbidden))

    def test_declares_all_deploy_studio_artifacts(self) -> None:
        contract = json.loads((ROOT / "terraform" / "deploy-studio.json").read_text(encoding="utf-8"))

        self.assertEqual(
            set(contract["artifacts"]),
            {"adb_wallet.zip", "ssh-private-key.pem", "connection-summary.txt"},
        )


if __name__ == "__main__":
    unittest.main()
