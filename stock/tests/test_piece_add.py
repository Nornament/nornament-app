from datetime import date

from django.urls import reverse

from stock.models import Piece, StockMovement, StockState, Style


def test_a_piece_is_added_from_the_list_and_lands_in_its_bom_editor(client, admin_user_, piece, locations):
    client.force_login(admin_user_)
    assert reverse("stock:piece_new") in client.get(reverse("stock:piece_list")).content.decode()

    response = client.post(reverse("stock:piece_new"), {
        "jewel_code": "ER00999",
        "style": Style.objects.get(style_code="ER00738").pk,
        "metal_purity": "18K",
        "location": locations["MUM"].pk,
        "received_on": date.today().isoformat(),
    })
    assert response.status_code == 302, response.content.decode()[:2000]
    assert response["Location"] == reverse("stock:piece_bom_edit", kwargs={"jewel_code": "ER00999"})
    added = Piece.objects.get(jewel_code="ER00999")
    assert added.stock_state == StockState.IN_STOCK and added.location == locations["MUM"]
    assert StockMovement.objects.filter(piece=added).exists()  # received, not just placed


def test_a_role_that_cannot_edit_boms_is_not_offered_the_button(client, sales_user):
    client.force_login(sales_user)
    assert reverse("stock:piece_new") not in client.get(reverse("stock:piece_list")).content.decode()
