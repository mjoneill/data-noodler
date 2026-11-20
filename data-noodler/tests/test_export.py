"""The file, its sidecar, and the receipt.

The sidecar exists because the conversation does not survive. Someone opening
a CSV six months later has no transcript, so provenance -- which property,
which dates, was it sampled, was it truncated -- has to travel with the file.
"""

import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import export

COLS = ["date", "screenPageViews"]
ROWS = [["2026-08-06", "412"], ["2026-08-07", "395"], ["2026-08-08", "501"]]
META = {
    "source": "ga4",
    "property_id": "314159265",
    "metrics": ["screenPageViews"],
    "dimensions": ["date"],
    "date_range": {"start": "2026-08-06", "end": "2026-08-08"},
    "sampled": False,
    "row_limit_hit": False,
}


class TestWriteExport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "out.csv")

    def test_writes_a_header_and_every_row(self):
        export.write_export(self.p, COLS, ROWS, META)
        with open(self.p) as f:
            lines = [l.rstrip("\n") for l in f]
        self.assertEqual(lines[0], "date,screenPageViews")
        self.assertEqual(len(lines), 4)

    def test_receipt_reports_the_real_row_count(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(r["row_count"], 3)

    def test_receipt_carries_the_metadata_it_was_given(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(r["property_id"], "314159265")
        self.assertFalse(r["sampled"])
        self.assertFalse(r["row_limit_hit"])

    def test_receipt_names_both_files(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(r["path"], self.p)
        self.assertEqual(r["meta_path"], self.p[:-4] + ".meta.json")

    def test_sidecar_is_written_and_matches_the_receipt(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        with open(r["meta_path"]) as f:
            side = json.load(f)
        self.assertEqual(side, r)

    def test_preview_is_capped_and_included(self):
        r = export.write_export(self.p, COLS, ROWS, META, preview_rows=2)
        self.assertEqual(r["preview"], ROWS[:2])

    def test_retrieved_at_is_present_and_iso(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertRegex(r["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:")

    def test_zero_rows_still_writes_the_file_with_a_header(self):
        r = export.write_export(self.p, COLS, [], META)
        self.assertEqual(r["row_count"], 0)
        self.assertTrue(os.path.exists(self.p))
        with open(self.p) as f:
            self.assertEqual(f.read().strip(), "date,screenPageViews")

    def test_refuses_an_existing_file_without_overwrite(self):
        export.write_export(self.p, COLS, ROWS, META)
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, META)

    def test_a_value_containing_a_comma_is_quoted(self):
        r = export.write_export(self.p, ["q", "clicks"],
                                [["shoes, red", "4"]], META)
        with open(self.p) as f:
            self.assertIn('"shoes, red"', f.read())
        self.assertEqual(r["row_count"], 1)

    def test_write_failure_leaves_no_partial_file(self):
        # A directory where the file should go makes os.replace() fail.
        # overwrite=True is required: without it check_writable rejects the
        # path on the already-exists rule and the test passes without ever
        # reaching the write, testing nothing it claims to test.
        os.makedirs(os.path.join(self.d, "blocked.csv"))
        with self.assertRaises(export.ExportError):
            export.write_export(os.path.join(self.d, "blocked.csv"),
                                COLS, ROWS, META, overwrite=True)
        # The temp file must not survive the failure.
        self.assertFalse(os.path.exists(
            os.path.join(self.d, "blocked.csv.ga-tmp")))

    def test_row_count_mismatch_with_columns_is_rejected(self):
        with self.assertRaises(export.ExportError) as ctx:
            export.write_export(self.p, COLS, [["only-one-value"]], META)
        self.assertIn("columns", str(ctx.exception))

    def test_non_json_serialisable_meta_raises_export_error(self):
        bad_meta = dict(META, when=datetime.date(2026, 9, 3))
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, bad_meta)

    def test_non_json_serialisable_meta_leaves_no_tmp_file(self):
        bad_meta = dict(META, when=datetime.date(2026, 9, 3))
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, bad_meta)
        self.assertFalse(os.path.exists(self.p + ".ga-tmp"))
        meta_path = self.p[:-4] + ".meta.json"
        # No truncated, invalid-JSON sidecar left behind either: the error
        # message says the provenance record is missing, so it must be.
        self.assertFalse(os.path.exists(meta_path))
        self.assertFalse(os.path.exists(meta_path + ".ga-tmp"))

    def test_preview_rows_is_capped_however_many_are_asked_for(self):
        # The whole point of exporting is that large results never pass
        # through a context window. preview_rows=3000 would put 3000 rows in
        # the receipt AND duplicate them into the sidecar, defeating it.
        rows = [[f"2026-08-{i:02d}", str(i)] for i in range(1, 29)]
        r = export.write_export(self.p, COLS, rows, META, preview_rows=3000)
        self.assertEqual(len(r["preview"]), export.MAX_PREVIEW_ROWS)
        self.assertEqual(r["row_count"], 28)

    def test_a_negative_preview_count_yields_no_preview(self):
        r = export.write_export(self.p, COLS, ROWS, META, preview_rows=-5)
        self.assertEqual(r["preview"], [])

    def test_non_ascii_values_round_trip_as_utf8(self):
        rows = [["café", "4"], ["日本語", "9"]]
        export.write_export(self.p, ["q", "clicks"], rows, META)
        with open(self.p, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("café", content)
        self.assertIn("日本語", content)


class TestTempPathsAreNotWritableThrough(unittest.TestCase):
    """The destination is validated; the temp file it is written through is
    not addressable by the caller at all, and used to be opened with a plain
    open(). A symlink planted at `<destination>.ga-tmp` was therefore
    followed, truncating and overwriting whatever it pointed at -- exactly
    the failure that destroyed a Homebrew interpreter on 2026-09-02 and gave
    sessions.py its reason to exist, reachable through a path sessions.py
    never sees.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "out.csv")
        self.victim = os.path.join(self.d, "victim.txt")
        with open(self.victim, "w") as f:
            f.write("precious")

    def _victim_text(self):
        with open(self.victim) as f:
            return f.read()

    def test_a_symlinked_csv_tmp_is_refused_and_the_victim_survives(self):
        os.symlink(self.victim, self.p + ".ga-tmp")
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(self._victim_text(), "precious")
        self.assertFalse(os.path.exists(self.p))

    def test_a_symlinked_sidecar_tmp_is_refused_and_the_victim_survives(self):
        meta_path = self.p[:-4] + ".meta.json"
        os.symlink(self.victim, meta_path + ".ga-tmp")
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(self._victim_text(), "precious")
        # The CSV itself was written before the sidecar failed; the sidecar
        # must not exist, because the error says the record is missing.
        self.assertFalse(os.path.exists(meta_path))

    def test_a_dangling_symlink_at_the_tmp_path_is_refused_too(self):
        # O_CREAT|O_EXCL must refuse a symlink whether or not its target
        # exists -- otherwise a link planted ahead of time creates the
        # victim file rather than merely overwriting one.
        target = os.path.join(self.d, "not-yet-there.txt")
        os.symlink(target, self.p + ".ga-tmp")
        with self.assertRaises(export.ExportError):
            export.write_export(self.p, COLS, ROWS, META)
        self.assertFalse(os.path.exists(target))

    def test_a_leftover_tmp_file_is_refused_not_silently_overwritten(self):
        leftover = self.p + ".ga-tmp"
        with open(leftover, "w") as f:
            f.write("half a previous run")
        with self.assertRaises(export.ExportError) as ctx:
            export.write_export(self.p, COLS, ROWS, META)
        message = str(ctx.exception).lower()
        self.assertIn("already there", message)
        # "delete it" is not recourse Claude Desktop's chat harness can take
        # -- it has no shell -- so the message must also name the one
        # workaround that needs no shell at all: exporting to a different
        # filename.
        self.assertIn("different filename", message)
        with open(leftover) as f:
            self.assertEqual(f.read(), "half a previous run")

    def test_an_ordinary_write_still_succeeds_and_leaves_no_tmp_files(self):
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(r["row_count"], 3)
        self.assertTrue(os.path.exists(self.p))
        self.assertTrue(os.path.exists(r["meta_path"]))
        self.assertFalse(os.path.exists(self.p + ".ga-tmp"))
        self.assertFalse(os.path.exists(r["meta_path"] + ".ga-tmp"))

    def test_a_second_export_over_the_same_path_still_works(self):
        # The tmp file must actually be consumed by os.replace, or O_EXCL
        # would make every export after the first one fail.
        export.write_export(self.p, COLS, ROWS, META)
        r = export.write_export(self.p, COLS, ROWS, META, overwrite=True)
        self.assertEqual(r["row_count"], 3)


class TestExclusiveOpenOnEveryPlatform(unittest.TestCase):
    """The symlink guard must survive the port, not be deleted by it.

    os.O_NOFOLLOW does not exist on Windows, so export.py raised
    AttributeError on the first export there. The cheap fix is to delete the
    flag, and that would be the wrong one: this guard exists because on
    2026-09-02 an agent redirected output through a symlink and truncated
    Homebrew's python3.14, breaking every MCP server on the machine.

    Measured rather than assumed: O_CREAT|O_EXCL alone already refuses a
    symlink, on POSIX by specification and on Windows because CREATE_NEW
    fails when the name exists at all. So the guarantee lives in O_EXCL and
    O_NOFOLLOW is redundancy -- worth keeping where it exists, safe to be
    without where it does not. That is the difference between porting a guard
    and dropping one.
    """

    def _flags_without_nofollow(self):
        return export.EXCLUSIVE_FLAGS & ~getattr(os, "O_NOFOLLOW", 0)

    def test_the_flag_set_includes_nofollow_where_the_platform_has_it(self):
        if hasattr(os, "O_NOFOLLOW"):
            self.assertTrue(export.EXCLUSIVE_FLAGS & os.O_NOFOLLOW,
                            "POSIX has O_NOFOLLOW and it is not being used")

    def test_the_flag_set_always_carries_excl_and_creat(self):
        # If this ever stops holding, the guard is gone on every platform.
        self.assertTrue(export.EXCLUSIVE_FLAGS & os.O_EXCL)
        self.assertTrue(export.EXCLUSIVE_FLAGS & os.O_CREAT)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlink support")
    def test_a_planted_symlink_is_refused_without_nofollow_too(self):
        # The Windows flag set, exercised on this machine. This is the
        # assertion that makes dropping O_NOFOLLOW there defensible.
        d = tempfile.mkdtemp()
        target = os.path.join(d, "precious")
        with open(target, "w", encoding="utf-8") as f:
            f.write("do not overwrite me")
        link = os.path.join(d, "planted")
        os.symlink(target, link)

        with self.assertRaises(OSError):
            os.open(link, self._flags_without_nofollow(), 0o644)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "do not overwrite me")

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlink support")
    def test_export_refuses_to_write_through_a_symlinked_destination(self):
        # End to end through the real code path, not just the flags.
        d = tempfile.mkdtemp()
        target = os.path.join(d, "precious.csv")
        with open(target, "w", encoding="utf-8") as f:
            f.write("original")
        link = os.path.join(d, "report.csv")
        os.symlink(target, link)

        with self.assertRaises(Exception):
            export._open_exclusively(link)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "original")


class TestTheReceiptKeepsTheTotal(unittest.TestCase):
    """A regression the #6 tests could not see.

    #6 put the query's total into meta as row_count. write_export then
    overwrote row_count with the number of rows WRITTEN, so a capped export of
    100 out of 23,000 reached the receipt and the sidecar saying 100 -- and the
    23,000 was gone. You could tell it was capped, not by how much. The #6
    tests checked meta before it reached write_export, which is exactly the
    seam the value fell through. This one checks the receipt.
    """

    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "x.csv")

    def test_rows_matched_survives_into_receipt_and_sidecar(self):
        meta = dict(META, rows_matched=23000, rows_fetched=100,
                    incomplete_reason="caller_limit", row_limit_hit=True)
        r = export.write_export(self.p, COLS, ROWS, meta)
        self.assertEqual(r["rows_matched"], 23000)
        with open(self.p[:-4] + ".meta.json", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rows_matched"], 23000)

    def test_row_count_still_means_rows_written(self):
        # Existing readers depend on this meaning; it is not repurposed.
        r = export.write_export(self.p, COLS, ROWS, META)
        self.assertEqual(r["row_count"], len(ROWS))


class TestNextStep(unittest.TestCase):
    """What the model should do with this export, as the first thing it reads.

    Michael, 2026-10-05: "most analysts will actually WANT the full data, and
    cutoffs are going to be a headache." A model given rows decides by itself
    whether to cut them, and a model given a limit parameter invents a number --
    a colleague's session announced it had "only the first 1000 rows" of
    something.

    The receipt is the one channel that reliably arrives at the moment of
    decision: descriptions can be deferred and instructions dropped, but a tool's
    result is always read. So the policy is stated there, first:

      cutoffs never touch the DATA, only what is shown in chat.
    """

    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "x.csv")

    def _rows(self, n):
        return [[f"q{i}", str(i)] for i in range(n)]

    def _receipt(self, rows, **meta):
        return export.write_export(self.p, ["q", "clicks"], rows,
                                   dict(META, **meta))

    def test_next_step_is_the_first_key_the_model_reads(self):
        r = self._receipt(self._rows(3))
        self.assertEqual(next(iter(r)), "next_step")

    def test_a_small_complete_export_needs_no_instruction(self):
        self.assertIsNone(self._receipt(self._rows(3))["next_step"])

    def test_a_large_complete_export_says_ask_rather_than_cut(self):
        n = export.CHAT_ROW_THRESHOLD + 1
        step = self._receipt(self._rows(n))["next_step"]
        self.assertIn("Complete", step)
        self.assertIn(f"{n:,}", step)
        self.assertIn("ask", step.lower())
        self.assertIn("every row", step.lower(),
                      "must say the file keeps everything, or 'cut' reads as "
                      "permission to drop data")

    def test_the_threshold_is_twenty_five_hundred(self):
        self.assertEqual(export.CHAT_ROW_THRESHOLD, 2500)
        self.assertIsNone(self._receipt(self._rows(2500))["next_step"])

    # #1993 review (indigo): duplicate_rows must reach the FIRST field, or a
    # doubled file still reads all-clear to an agent that stops there.
    def test_repeated_rows_say_do_not_analyse_first(self):
        step = self._receipt(self._rows(4), duplicate_rows=2)["next_step"]
        self.assertTrue(step.startswith("REPEATED ROWS"), step)
        self.assertIn("2", step)
        self.assertIn("do not analyse", step.lower())

    def test_repeated_rows_outrank_a_cap(self):
        step = self._receipt(self._rows(100), duplicate_rows=1,
                             rows_matched=23000,
                             incomplete_reason="caller_limit",
                             row_limit_hit=True)["next_step"]
        self.assertTrue(step.startswith("REPEATED ROWS"), step)

    def test_repeated_rows_outrank_a_large_complete_file(self):
        n = export.CHAT_ROW_THRESHOLD + 1
        step = self._receipt(self._rows(n), duplicate_rows=5)["next_step"]
        self.assertTrue(step.startswith("REPEATED ROWS"), step)

    def test_zero_repeats_change_nothing(self):
        self.assertIsNone(
            self._receipt(self._rows(3), duplicate_rows=0)["next_step"])

    def test_a_cap_the_caller_chose_says_rerun_without_one(self):
        step = self._receipt(self._rows(100), rows_matched=23000,
                             incomplete_reason="caller_limit",
                             row_limit_hit=True)["next_step"]
        self.assertTrue(step.startswith("CAPPED"), step)
        self.assertIn("100 of 23,000", step)
        self.assertIn("without a limit", step)
        self.assertIn("user asked", step,
                      "a cap the user DID ask for is legitimate; say so")

    def test_a_search_console_row_limit_is_a_cap_too(self):
        step = self._receipt(self._rows(50), source="gsc_search_analytics",
                             row_limit_hit=True)["next_step"]
        self.assertTrue(step.startswith("CAPPED"), step)

    def test_a_server_that_stopped_short_is_incomplete_not_capped(self):
        step = self._receipt(self._rows(5), rows_matched=23000,
                             incomplete_reason="server_stopped",
                             row_limit_hit=True)["next_step"]
        self.assertTrue(step.startswith("INCOMPLETE"), step)
        self.assertNotIn("without a limit", step,
                         "re-running without a limit cannot fix this")

    def test_a_partial_url_inspection_is_incomplete(self):
        step = self._receipt(self._rows(5), stopped_reason="quota exhausted")[
            "next_step"]
        self.assertTrue(step.startswith("INCOMPLETE"), step)
