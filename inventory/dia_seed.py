"""The diamond master lists as the prototype read them (``build_dia.py``), as data.

Ranges carry the single grades they stand for, so a filter on "G" finds a line
recorded as F-G-H. These are the prototype's readings, not the owner's rulings:
Settings is where they are corrected, and loading again never overwrites a
correction.
"""
CATEGORIES = ["Natural Diamond", "HPHT Lab Grown", "Lab Grown (CVD?)", "Solitaire", "Foil Polki"]

COLOUR_LADDER = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P",
                 "Q-R", "S-T", "U-V", "W-X", "Y-Z"]
CLARITY_LADDER = ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]

COLOUR_RANGES = {"D-E-F": "D E F", "E-F": "E F", "F-G-H": "F G H", "G-H": "G H",
                 "I-J": "I J", "K-L": "K L", "M-N": "M N"}
CLARITY_RANGES = {"VVS-VS": "VVS1 VVS2 VS1 VS2", "VS-SI": "VS1 VS2 SI1 SI2",
                  "SI-I": "SI1 SI2 SI3 I1", "I1-I2": "I1 I2"}

FANCY = ["Fancy Yellow", "Fancy Pink", "Fancy Orange", "Fancy Green",
         "Fancy Blue", "Fancy Brown", "Fancy Black", "Fancy Grey"]

#: non-overlapping, in the order the Size row shows them; "?" is a size that fits none
BANDS = ["-2", "+2-6", "+6-11", "11-20", "20+", "carat band", "?"]


def load(DiamondTerm):
    """Idempotent: a value already there keeps whatever it has been corrected to."""
    def put(kind, value, sort, expands_to=""):
        DiamondTerm.objects.get_or_create(kind=kind, value=value,
                                          defaults={"sort": sort, "expands_to": expands_to})

    for n, value in enumerate(CATEGORIES):
        put("category", value, n)
    for n, value in enumerate(COLOUR_LADDER):
        put("colour", value, n)
    for n, (value, grades) in enumerate(COLOUR_RANGES.items()):
        put("colour", value, 100 + n, grades)
    for n, value in enumerate(FANCY):
        put("colour", value, 200 + n)
    for n, value in enumerate(CLARITY_LADDER):
        put("clarity", value, n)
    for n, (value, grades) in enumerate(CLARITY_RANGES.items()):
        put("clarity", value, 100 + n, grades)
    for n, value in enumerate(BANDS):
        put("band", value, n)
