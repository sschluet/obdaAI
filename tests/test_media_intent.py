import pytest
from hub.media_intent import image, pages


def test_explicit_pdf_order_and_rotation_are_bound_to_user_numbers():
    goal = (
        "Erstelle genau zwei Ausgabeseiten: zuerst Originalseite 2, danach Originalseite 1. "
        "Drehe die erste Ausgabeseite um 90 Grad im Uhrzeigersinn."
    )
    assert pages(goal) == [
        {"source": 0, "page": 2, "rotation": 90},
        {"source": 0, "page": 1, "rotation": 0},
    ]
    assert (
        pages("Erstelle PDF mit Seiten 3,1. Drehe Seite 3 um 90 Grad gegen den Uhrzeigersinn.")[0][
            "rotation"
        ]
        == 270
    )
    assert [p["page"] for p in pages("PDF mit Seiten 3-1")] == [3, 2, 1]
    assert pages("PDF mit allen Seiten") is None
    with pytest.raises(ValueError):
        pages("PDF mit Seiten 1-200")


def test_explicit_crop_coordinates_and_dimensions_do_not_come_from_model():
    assert image("Schneide auf die rechte Hälfte und skaliere auf 128 mal 128 Pixel")["tiles"][0][
        "crop"
    ] == [0.5, 0, 1, 1]
    assert image(
        "linker Rand 50 Prozent, oben 0 Prozent, rechts 100 Prozent, unten 100 Prozent; "
        "auf 128 mal 128 Pixel"
    )["tiles"][0]["crop"] == [0.5, 0, 1, 1]
    assert image("Schneide das Gesicht aus dem Bild") is None


def test_split_is_bound_only_to_explicit_user_boundaries():
    from hub.media_intent import split_after

    assert split_after("Teile jede Ausgabeseite in Einzel-PDFs", 3) == [1, 2]
    assert split_after("Trenne nach Ausgabeseiten 1 und 3", 4) == [1, 3]
    assert split_after("Erstelle eine Zusammenfassung", 4) is None
    with pytest.raises(ValueError):
        split_after("Teile jede Seite in Einzel-PDFs", 21)
