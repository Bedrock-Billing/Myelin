"""
UB04 Form Field Coordinates

Each entry maps a field key to (x, y) in standard PDF points.
Origin (0, 0) is at bottom-left. Page size is 684 x 864 pts.

The bundled template (ub04_blank.pdf) has been normalized to a standard
MediaBox [0, 0, 684, 864], so these coordinates can be used directly
with reportlab and merged without any MediaBox patching.
"""

# Page dimensions
PAGE_WIDTH = 684
PAGE_HEIGHT = 864

# Service line y-positions (lines 1-22 are service lines, line 23 is page/date/totals)
_LINE_Y: dict[int, float] = {
    1: 603,
    2: 591,
    3: 579,
    4: 567,
    5: 555,
    6: 543,
    7: 531,
    8: 519,
    9: 507,
    10: 495,
    11: 483,
    12: 471,
    13: 459,
    14: 447,
    15: 435,
    16: 423,
    17: 411,
    18: 399,
    19: 387,
    20: 375,
    21: 363,
    22: 351,
    23: 336,
}


def _line_y(line_num: int) -> float:
    """Get y coordinate for a service line row (1-based, max 23)."""
    return _LINE_Y.get(line_num, 603 - (line_num - 1) * 12.0)


# Column x-positions for service lines (FL 42-49)
_COL_X = {
    "FL42": 54,  # Revenue code
    "FL43": 91,  # Description
    "FL44": 266,  # HCPCS / Rate / HIPPS code
    "FL45": 381,  # Service date
    "FL46": 446,  # Service units
    "FL47": 496,  # Total charges
    "FL48": 571,  # Non-covered charges
    "FL49": 622,  # (unlabeled)
}

# Format: "field_key": (x, y)
COORDINATES: dict[str, tuple[float, float]] = {
    # ── FL 1: Provider name and address ──
    "FL1_name": (56, 805),
    "FL1_addr1": (56, 793),
    "FL1_addr2": (56, 781),
    "FL1_city_st_zip": (56, 769),
    # "FL1_phone": (112, 775),
    # ── FL 3a: Patient control number ──
    "FL3a": (431, 805),
    # ── FL 3b: Medical record number ──
    "FL3b": (431, 793),
    # ── FL 4: Type of bill ──
    "FL4": (612, 793),
    # ── FL 5: Federal tax number ──
    "FL5": (410, 769),
    # ── FL 6: Statement covers period ──
    "FL6_from": (483, 769),
    "FL6_thru": (535, 769),
    # ── FL 8: Patient name ──
    "FL8a": (130, 758),
    "FL8b": (56, 745),
    # ── FL 9: Patient address ──
    "FL9a": (345, 758),
    "FL9b": (273, 745),
    "FL9c": (510, 745),
    "FL9d": (540, 745),
    "FL9e": (618, 745),
    # ── FL 10-17: Patient demographics / admission ──
    "FL10": (52, 722),
    "FL11": (115, 722),
    "FL12": (140, 722),
    "FL13": (180, 722),
    "FL14": (200, 722),
    "FL15": (220, 722),
    "FL16": (244, 722),
    "FL17": (265, 722),
    # ── FL 18-28: Condition codes ──
    "FL18": (288, 722),
    "FL19": (310, 722),
    "FL20": (330, 722),
    "FL21": (352, 722),
    "FL22": (374, 722),
    "FL23": (394, 722),
    "FL24": (416, 722),
    "FL25": (438, 722),
    "FL26": (460, 722),
    "FL27": (482, 722),
    "FL28": (504, 722),
    # ── FL 29: ACDT state ──
    "FL29": (526, 722),
    # ── FL 31-34: Occurrence codes and dates ──
    "FL31a_code": (48, 696),
    "FL31a_date": (72, 696),
    "FL32a_code": (120, 696),
    "FL32a_date": (145, 696),
    "FL33a_code": (192, 696),
    "FL33a_date": (218, 696),
    "FL34a_code": (263, 696),
    "FL34a_date": (290, 696),
    "FL31b_code": (48, 684),
    "FL31b_date": (72, 684),
    "FL32b_code": (120, 684),
    "FL32b_date": (145, 684),
    "FL33b_code": (192, 684),
    "FL33b_date": (218, 684),
    "FL34b_code": (263, 684),
    "FL34b_date": (290, 684),
    # ── FL 35-36: Occurrence span codes ──
    "FL35a_code": (336, 696),
    "FL35a_from": (370, 696),
    "FL35a_thru": (420, 696),
    "FL36a_code": (460, 696),
    "FL36a_from": (490, 696),
    "FL36a_thru": (540, 696),
    "FL35b_code": (336, 684),
    "FL35b_from": (370, 684),
    "FL35b_thru": (420, 684),
    "FL36b_code": (460, 684),
    "FL36b_from": (490, 684),
    "FL36b_thru": (540, 684),
    # ── FL 38: Responsible party ──
    "FL38": (52, 668),
    # ── FL 39-41: Value codes and amounts ──
    "FL39a_code": (358, 660),
    "FL39a_amount": (386, 660),
    "FL39b_code": (358, 648),
    "FL39b_amount": (386, 648),
    "FL39c_code": (358, 636),
    "FL39c_amount": (386, 636),
    "FL39d_code": (358, 624),
    "FL39d_amount": (386, 624),
    "FL40a_code": (452, 660),
    "FL40a_amount": (476, 660),
    "FL40b_code": (452, 648),
    "FL40b_amount": (476, 648),
    "FL40c_code": (452, 636),
    "FL40c_amount": (476, 636),
    "FL40d_code": (452, 624),
    "FL40d_amount": (476, 624),
    "FL41a_code": (545, 660),
    "FL41a_amount": (570, 660),
    "FL41b_code": (545, 648),
    "FL41b_amount": (570, 648),
    "FL41c_code": (545, 636),
    "FL41c_amount": (570, 636),
    "FL41d_code": (545, 624),
    "FL41d_amount": (570, 624),
    # ── FL 50A-C: Payer names ──
    "FL50A": (52, 312),
    "FL50B": (52, 300),
    "FL50C": (52, 288),
    # ── FL 51A-C: Health plan ID ──
    "FL51A": (236, 312),
    "FL51B": (236, 300),
    "FL51C": (236, 288),
    # ── FL 56: NPI ──
    "FL56": (535, 324),
    # ── FL 57: Other provider ID ──
    "FL57": (535, 315),
    # ── FL 58A-C: Insured's name ──
    "FL58A": (52, 266),
    "FL58B": (52, 254),
    "FL58C": (52, 242),
    # ── FL 60A-C: Insured's unique ID ──
    "FL60A": (286, 266),
    "FL60B": (286, 254),
    "FL60C": (286, 242),
    # ── FL 63A-C: Treatment authorization codes ──
    "FL63A": (52, 220),
    "FL63B": (52, 208),
    "FL63C": (52, 196),
    # ── FL 64A-C: Document control number ──
    "FL64A": (276, 220),
    "FL64B": (276, 208),
    "FL64C": (276, 196),
    # ── FL 65A-C: Employer name ──
    "FL65A": (460, 220),
    "FL65B": (460, 208),
    "FL65C": (460, 196),
    # ── FL 66: DX version qualifier ──
    "FL66": (48, 172),
    # ── FL 67: Principal diagnosis ──
    "FL67": (60, 182),
    # ── FL 67A-H: Secondary diagnoses row 1 ──
    "FL67A": (120, 182),
    "FL67B": (180, 182),
    "FL67C": (240, 182),
    "FL67D": (300, 182),
    "FL67E": (360, 182),
    "FL67F": (420, 182),
    "FL67G": (480, 182),
    "FL67H": (540, 182),
    # ── FL 67I-Q: Secondary diagnoses row 2 ──
    "FL67I": (60, 172),
    "FL67J": (120, 172),
    "FL67K": (180, 172),
    "FL67L": (240, 172),
    "FL67M": (300, 172),
    "FL67N": (360, 172),
    "FL67O": (420, 172),
    "FL67P": (480, 172),
    "FL67Q": (540, 172),
    # ── FL 69: Admitting diagnosis ──
    "FL69": (86, 158),
    # ── FL 70a-c: Patient reason for visit DX ──
    "FL70a": (181, 158),
    "FL70b": (226, 158),
    "FL70c": (275, 158),
    # ── FL 71: PPS code ──
    "FL71": (345, 158),
    # ── FL 72a-c: External cause of injury ──
    "FL72a": (396, 158),
    "FL72b": (461, 158),
    "FL72c": (526, 158),
    # ── FL 74: Principal procedure code and date ──
    "FL74_code": (52, 134),
    "FL74_date": (120, 134),
    # ── FL 74a-e: Other procedures ──
    "FL74a_code": (166, 134),
    "FL74a_date": (226, 134),
    "FL74b_code": (276, 134),
    "FL74b_date": (336, 134),
    "FL74c_code": (52, 110),
    "FL74c_date": (120, 110),
    "FL74d_code": (166, 110),
    "FL74d_date": (226, 110),
    "FL74e_code": (276, 110),
    "FL74e_date": (336, 110),
    # ── FL 76: Attending physician ──
    "FL76_npi": (472, 146),
    "FL76_qual": (560, 146),
    "FL76_last": (440, 135),
    "FL76_first": (560, 135),
    # ── FL 77: Operating physician ──
    "FL77_npi": (472, 122),
    "FL77_last": (440, 110),
    "FL77_first": (560, 110),
    # ── FL 78-79: Other physicians ──
    "FL78_npi": (472, 100),
    "FL79_npi": (472, 75),
    # ── FL 80: Remarks ──
    "FL80": (52, 85),
}

# ── Service line coordinates (FL 42-49) ──
for _i in range(1, 23):
    _y = _line_y(_i)
    COORDINATES[f"FL42_{_i}"] = (_COL_X["FL42"], _y)
    COORDINATES[f"FL43_{_i}"] = (_COL_X["FL43"], _y)
    COORDINATES[f"FL44_{_i}"] = (_COL_X["FL44"], _y)
    COORDINATES[f"FL45_{_i}"] = (_COL_X["FL45"], _y)
    COORDINATES[f"FL46_{_i}"] = (_COL_X["FL46"], _y)
    COORDINATES[f"FL47_{_i}"] = (_COL_X["FL47"], _y)
    COORDINATES[f"FL48_{_i}"] = (_COL_X["FL48"], _y)
    COORDINATES[f"FL49_{_i}"] = (_COL_X["FL49"], _y)

# Line 23 page/date/totals fields
COORDINATES["FL42_page"] = (116, 340)
COORDINATES["FL42_pages_total"] = (156, 340)
COORDINATES["FL44_creation_date"] = (381, 338)
COORDINATES["FL47_total_charges"] = (_COL_X["FL47"], 338)
COORDINATES["FL48_total_non_covered_charges"] = (_COL_X["FL48"], 338)

# Font
FONT_NAME = "Courier"
FONT_SIZE = 7
FONT_SIZE_SMALL = 6
