"""Upload → review → commit for the diamond register, the stones importer's shape."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_MASTERS
from stock.models import ImportBatch
from stock.services import ServiceError
from stock.views import _batch_workbook, _store_workbook

from .importers import dia_plan, diamonds
from .models import DiamondTerm
from .views_diamonds import dia_page

SOURCE = "DIAMONDS"


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_home(request):
    if request.method == "POST":
        upload = request.FILES.get("workbook")
        if upload is None:
            messages.error(request, "Choose a workbook first.")
            return redirect("inventory:dia_import_home")
        problems = diamonds.header_problems(upload)
        if problems:
            messages.error(request, f"That is not the diamond register. {problems[0]}")
            return redirect("inventory:dia_import_home")
        upload.seek(0)
        try:
            asset = _store_workbook(upload, request.user)
        except Exception as error:
            messages.error(request, f"Could not store the file. {error}")
            return redirect("inventory:dia_import_home")
        batch = ImportBatch.objects.create(media=asset, source=SOURCE, created_by=request.user,
                                           status=ImportBatch.Status.REVIEWING)
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    recent = ImportBatch.objects.filter(source=SOURCE).select_related("media")[:10]
    return dia_page(request, "inventory/diamonds/import_home.html", dtab="import", recent=recent)


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_review(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source=SOURCE)
    rows = diamonds.parse(_batch_workbook(batch))
    plan = dia_plan.analyse(rows, batch.decisions)
    if request.method == "POST" and batch.status == ImportBatch.Status.REVIEWING:
        batch.decisions = dia_plan.read_decisions(request.POST, plan, batch.decisions)
        batch.save(update_fields=["decisions"])
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    terms = {kind: list(DiamondTerm.objects.filter(kind=kind).values_list("value", flat=True))
             for kind in (DiamondTerm.SHAPE, DiamondTerm.COLOUR, DiamondTerm.CLARITY)}
    return dia_page(request, "inventory/diamonds/import_review.html", dtab="import", batch=batch, plan=plan,
                    counts=plan.counts(), blocked=[i for i in plan.items if i.problem and i.action != "skip"],
                    recounts=[i for i in plan.items if i.recount], terms=terms)


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
@require_POST
def import_commit(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source=SOURCE)
    claimable = [ImportBatch.Status.REVIEWING, ImportBatch.Status.FAILED]
    if not ImportBatch.objects.filter(pk=batch.pk, status__in=claimable).update(status=ImportBatch.Status.COMMITTING):
        messages.error(request, "That import has already been committed, or is being committed now.")
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    try:
        plan = dia_plan.analyse(diamonds.parse(_batch_workbook(batch)), batch.decisions)
        result = dia_plan.commit(plan, request.user, import_batch=batch)
    except ServiceError as error:
        batch.save(update_fields=["status"])        # back to what it was: rows still need deciding
        messages.error(request, error.messages[0])
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    except Exception as error:  # the transaction has already rolled back
        batch.status, batch.result = ImportBatch.Status.FAILED, {"error": str(error)}
        batch.save(update_fields=["status", "result"])
        messages.error(request, f"Import failed, nothing was written. {error}")
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    batch.status, batch.result, batch.finished_at = ImportBatch.Status.DONE, result, timezone.now()
    batch.save(update_fields=["status", "result", "finished_at"])
    messages.success(request, f"Imported: {result['created']} new, {result['updated']} updated, "
                              f"{result['recounted']} recounted, {result['zeroed']} set to zero, "
                              f"{result['codes']} new codes.")
    return redirect("inventory:diamonds")
