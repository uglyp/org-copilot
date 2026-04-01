"""企业权限纯函数单元测试（无需数据库）。"""

import unittest

from app.models.entities import Document, User
from app.services.permissions import (
    build_milvus_acl_filter,
    document_visible_to,
    escape_milvus_string,
)


class TestEscapeMilvusString(unittest.TestCase):
    def test_escapes_quote_and_backslash(self) -> None:
        self.assertEqual(escape_milvus_string(r'a"b\c'), r'a\"b\\c')


class TestBuildMilvusAclFilter(unittest.TestCase):
    def test_combines_kb_branch_and_level(self) -> None:
        u = User(
            id=1,
            username="x",
            hashed_password="h",
            branch="上海分行",
            role="user",
            security_level=2,
        )
        s = build_milvus_acl_filter(7, u, public_branch_label="公共")
        self.assertIn("kb_id == 7", s)
        self.assertIn('branch == "上海分行"', s)
        self.assertIn('branch == "公共"', s)
        self.assertIn("security_level <= 2", s)


class TestDocumentVisibleTo(unittest.TestCase):
    def _user(
        self,
        *,
        branch: str = "公共",
        security_level: int = 4,
        departments_json: list[str] | None = None,
    ) -> User:
        return User(
            id=1,
            username="u",
            hashed_password="h",
            branch=branch,
            role="user",
            security_level=security_level,
            departments_json=departments_json,
        )

    def test_public_branch_doc_visible_to_other_branch_user(self) -> None:
        doc = Document(
            id=1,
            kb_id=1,
            filename="f",
            storage_path="/p",
            branch="公共",
            security_level=1,
        )
        u = self._user(branch="北京分行")
        self.assertTrue(
            document_visible_to(doc, u, public_branch_label="公共"),
        )

    def test_other_branch_blocked(self) -> None:
        doc = Document(
            id=1,
            kb_id=1,
            filename="f",
            storage_path="/p",
            branch="上海分行",
            security_level=1,
        )
        u = self._user(branch="北京分行")
        self.assertFalse(
            document_visible_to(doc, u, public_branch_label="公共"),
        )

    def test_security_level_blocked(self) -> None:
        doc = Document(
            id=1,
            kb_id=1,
            filename="f",
            storage_path="/p",
            branch="公共",
            security_level=3,
        )
        u = self._user(security_level=2)
        self.assertFalse(
            document_visible_to(doc, u, public_branch_label="公共"),
        )

    def test_department_required(self) -> None:
        doc = Document(
            id=1,
            kb_id=1,
            filename="f",
            storage_path="/p",
            branch="公共",
            security_level=1,
            department="风控部",
        )
        u = self._user(departments_json=None)
        self.assertFalse(
            document_visible_to(doc, u, public_branch_label="公共"),
        )
        u2 = self._user(departments_json=["风控部"])
        self.assertTrue(
            document_visible_to(doc, u2, public_branch_label="公共"),
        )

    def test_admin_sees_any_document(self) -> None:
        doc = Document(
            id=1,
            kb_id=1,
            filename="f",
            storage_path="/p",
            branch="上海分行",
            security_level=4,
            department="风控部",
        )
        admin = User(
            id=9,
            username="adm",
            hashed_password="h",
            branch="公共",
            role="admin",
            security_level=1,
            departments_json=[],
        )
        self.assertTrue(
            document_visible_to(doc, admin, public_branch_label="公共"),
        )


class TestAdminMilvusFilter(unittest.TestCase):
    def test_admin_filter_is_kb_only(self) -> None:
        admin = User(
            id=1,
            username="a",
            hashed_password="h",
            branch="公共",
            role="admin",
            security_level=1,
        )
        s = build_milvus_acl_filter(42, admin, public_branch_label="公共")
        self.assertEqual(s, "kb_id == 42")


if __name__ == "__main__":
    unittest.main()
