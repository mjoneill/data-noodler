"""#2011 diagnostic, trial branch only: after a write through a planted
dangling link, does the link's TARGET exist?  Prints the answer either way."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import export

class Probe2011(unittest.TestCase):
    def test_probe(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "out.csv")
            target = os.path.join(d, "not-yet-there.txt")
            os.symlink(target, p + ".ga-tmp")
            outcome = "no error"
            try:
                export.write_export(p, ["a"], [["1"]], {"m": 1})
            except Exception as e:
                outcome = f"{type(e).__name__}: {e}"
            exists = os.path.exists(target)
            body = open(target).read(200) if exists else ""
            print(f"\nPROBE2011 outcome={outcome!r} target_exists={exists} "
                  f"link_still_link={os.path.islink(p + '.ga-tmp')} "
                  f"out_exists={os.path.exists(p)} out_is_link={os.path.islink(p)} "
                  f"out_realpath_is_target={os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(target))} "
                  f"target_head={body!r}", flush=True)
