from django.urls import path

from . import (
    views, views_assort, views_dia_import, views_dia_settings, views_diamonds, views_documents, views_ledger,
    views_lists, views_purchase,
)

app_name = "inventory"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("view/", views.set_view, name="set_view"),
    path("colours/<str:code>/", views.colour, name="colour"),
    path("batches/<int:pk>/", views.batch, name="batch"),
    path("import/", views.import_home, name="import_home"),
    path("import/<int:batch_id>/", views.import_review, name="import_review"),
    path("import/<int:batch_id>/commit/", views.import_commit, name="import_commit"),
    path("pouches/<str:ref>/", views.pouch, name="pouch"),
    path("pouches/<str:ref>/save/", views.pouch_save, name="pouch_save"),
    path("pouches/<str:ref>/price/", views.pouch_price, name="pouch_price"),
    path("pouches/<str:ref>/photos/", views.pouch_photos, name="pouch_photos"),
    path("pouches/<str:ref>/movements/", views_ledger.movements, name="movements"),
    path("pouches/<str:ref>/movements/post/", views_ledger.movement_post, name="movement_post"),
    path("pouches/<str:ref>/split/", views_assort.split, name="split"),
    path("pouches/<str:ref>/transfer/", views_assort.transfer, name="transfer"),
    path("purchases/new/", views_purchase.purchase, name="purchase"),
    path("documents/<int:pk>/", views_documents.document, name="document"),
    path("documents/<int:pk>/settle/", views_documents.document_settle, name="document_settle"),
    path("documents/<int:pk>/undo/", views_documents.document_undo, name="document_undo"),
    path("documents/<int:pk>/reverse/", views_documents.document_reverse, name="document_reverse"),
    path("job-work/", views_lists.job_work_list, name="job_work_list"),
    path("memos/", views_lists.memo_list, name="memo_list"),
    path("movements/", views_lists.recent, name="recent"),
    path("photos/<int:media_id>/", views.photo, name="photo"),
    path("diamonds/", views_diamonds.search, name="diamonds"),
    path("diamonds/settings/", views_dia_settings.settings_page, name="dia_settings"),
    path("diamonds/settings/terms/", views_dia_settings.term_add, name="dia_term_add"),
    path("diamonds/settings/terms/<int:pk>/rename/", views_dia_settings.term_rename, name="dia_term_rename"),
    path("diamonds/settings/terms/<int:pk>/delete/", views_dia_settings.term_delete, name="dia_term_delete"),
    path("diamonds/settings/terms/<int:pk>/expansion/", views_dia_settings.expansion, name="dia_expansion"),
    path("diamonds/settings/codes/<str:code>/", views_dia_settings.code_save, name="dia_code_save"),
    path("diamonds/settings/rates/", views_dia_settings.rate_save, name="dia_rate_save"),
    path("diamonds/settings/rates/ivy/", views_dia_settings.rates_ivy, name="dia_rates_ivy"),
    path("diamonds/settings/suppliers/", views_dia_settings.supplier_save, name="dia_supplier_save"),
    path("diamonds/settings/rights/", views_dia_settings.right_toggle, name="dia_right_toggle"),
    path("diamonds/import/", views_dia_import.import_home, name="dia_import_home"),
    path("diamonds/import/<int:batch_id>/", views_dia_import.import_review, name="dia_import_review"),
    path("diamonds/import/<int:batch_id>/commit/", views_dia_import.import_commit, name="dia_import_commit"),
]
