import os
import tempfile
import unittest
from pathlib import Path
from services.velour_owner_memory import OwnerMemoryShelf, OwnerMemoryError

class OwnerMemoryTests(unittest.TestCase):
    def test_default_denies_writes_and_reads(self):
        with tempfile.TemporaryDirectory() as root:
            shelf = OwnerMemoryShelf(Path(root) / "memory.sqlite3")
            with self.assertRaises(OwnerMemoryError):
                shelf.provision()
            self.assertFalse(shelf.path.exists())
            shelf.provision(owner_verified=True, owner_approved=True)
            with self.assertRaises(OwnerMemoryError):
                shelf.remember(session="s", subject="tiburon", note="car")
            with self.assertRaises(OwnerMemoryError):
                shelf.recall()

    def test_durable_across_new_instance_and_expires(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "memory.sqlite3"
            shelf = OwnerMemoryShelf(path)
            shelf.provision(owner_verified=True, owner_approved=True)
            memory_id = shelf.remember(
                session="founder-1", subject="Tiburon", note="The clutch is manual.",
                owner_verified=True, owner_approved=True, now=100, ttl_days=1)
            other = OwnerMemoryShelf(path)
            found = other.recall(subject="tiburon", owner_verified=True, now=101)
            self.assertEqual([memory_id], [x["id"] for x in found["items"]])
            self.assertEqual("owner_stated_not_independently_verified", found["truth_status"])
            self.assertEqual("none", found["authority"])
            self.assertEqual([], other.recall(subject="tiburon", owner_verified=True, now=86501)["items"])

    def test_forget_and_clear_require_owner_approval(self):
        with tempfile.TemporaryDirectory() as root:
            shelf = OwnerMemoryShelf(Path(root) / "mem.sqlite3")
            shelf.provision(owner_verified=True, owner_approved=True)
            memory_id = shelf.remember(session="s", subject="engine", note="2.0L",
                                       owner_verified=True, owner_approved=True, now=100000000)
            with self.assertRaises(OwnerMemoryError):
                shelf.forget(memory_id, owner_verified=True)
            self.assertTrue(shelf.forget(memory_id, owner_verified=True, owner_approved=True))
            self.assertFalse(shelf.forget(memory_id, owner_verified=True, owner_approved=True))
            self.assertEqual(0, shelf.purge(owner_verified=True, owner_approved=True))

    def test_rejects_world_readable_file_and_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "mem.sqlite3"
            shelf = OwnerMemoryShelf(path)
            shelf.provision(owner_verified=True, owner_approved=True)
            os.chmod(path, 0o644)
            with self.assertRaises(OwnerMemoryError):
                shelf.recall(owner_verified=True)
            os.chmod(path, 0o600)
            link = Path(root) / "link.sqlite3"
            link.symlink_to(path)
            with self.assertRaises(OwnerMemoryError):
                OwnerMemoryShelf(link).recall(owner_verified=True)

    def test_rejects_oversize_and_invalid_ttl(self):
        with tempfile.TemporaryDirectory() as root:
            shelf = OwnerMemoryShelf(Path(root) / "mem.sqlite3")
            shelf.provision(owner_verified=True, owner_approved=True)
            for note, ttl in (("x" * 2001, 1), ("ok", 0)):
                with self.assertRaises(ValueError):
                    shelf.remember(session="s", subject="test", note=note,
                                   owner_verified=True, owner_approved=True, ttl_days=ttl)

if __name__ == "__main__":
    unittest.main()
