# -*- coding: utf-8 -*-
"""Assembles the DBARS Project Defense & Codebase Mastery Document."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import style  # noqa: E402

MODULES = [
    ("s01_05", ["front_matter", "section_1"]),
    ("s02_03", ["section_2", "section_3"]),
    ("s04_05", ["section_4", "section_5"]),
    ("s06_09", ["section_6", "section_7", "section_8", "section_9"]),
    ("s10_12", ["section_10", "section_11", "section_12"]),
    ("s13_15", ["section_13", "section_14", "section_15"]),
    ("s16_20", ["section_16", "section_17", "section_18", "section_19", "section_20"]),
    ("s21_25", ["section_21", "section_22", "section_23", "section_24", "section_25"]),
    ("s26_30", ["section_26", "section_27", "section_28", "section_29", "section_30"]),
    ("s31_35", ["section_31", "section_32", "section_33", "section_34", "section_35"]),
    ("s36_39", ["section_36", "section_37", "section_38", "section_39"]),
    ("s40_42", ["section_40", "section_41", "section_42"]),
    ("appendix", ["appendices"]),
]


def main():
    doc = style.new_document()
    built = []
    for modname, funcs in MODULES:
        try:
            mod = __import__(modname)
        except ImportError:
            print("  [skip] %s not written yet" % modname)
            continue
        for fname in funcs:
            fn = getattr(mod, fname, None)
            if fn is None:
                print("  [skip] %s.%s missing" % (modname, fname))
                continue
            fn(doc)
            built.append("%s.%s" % (modname, fname))
    style.add_header(doc, "DBARS - Demand Based Bus Allocation & Routing System")
    style.add_page_numbers(doc)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "DBARS_Project_Defense_and_Codebase_Mastery.docx")
    out = os.path.abspath(out)
    doc.save(out)
    print("\nBuilt %d section functions" % len(built))
    print("Output: %s" % out)
    print("Size:   %.1f KB" % (os.path.getsize(out) / 1024.0))


if __name__ == "__main__":
    main()
