from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from decimal import Decimal
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle, 
    Location, UnloadLocation, OperationType, LossType,
    PartyType, LocationType, OperationDirection
)
from masterdata.forms import (
    ProductForm, PartyForm, DriverForm, VehicleTypeForm, VehicleForm,
    LocationForm, UnloadLocationForm, OperationTypeForm, LossTypeForm
)
from accounts.decorators import role_required
from audit.services import log_audit
from audit.models import AuditAction

# Helper for generic masterdata list & search
def paginate_and_search(request, queryset, search_fields):
    q = request.GET.get("q", "").strip()
    if q:
        query_filter = Q()
        for field in search_fields:
            query_filter |= Q(**{f"{field}__icontains": q})
        queryset = queryset.filter(query_filter)
    
    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return page_obj, q

# ----------------- Products -----------------
@login_required
def product_list(request):
    products = Product.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, products, ["name", "code", "description"])
    return render(request, "masterdata/product_list.html", {
        "page_obj": page_obj,
        "products": page_obj,
        "q": q,
        "title": "مدیریت محصولات و کالاهای باسکول",
    })

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def product_create(request):
    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.CREATE, "Product", obj.id, f"محصول {obj.name}", reason="تعریف محصول جدید")
            messages.success(request, f"محصول «{obj.name}» با موفقیت افزوده شد.")
            return redirect("masterdata:product_list")
    else:
        form = ProductForm()
    return render(request, "masterdata/product_form.html", {"form": form, "title": "افزودن محصول جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def product_edit(request, pk):
    obj = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.UPDATE, "Product", obj.id, f"محصول {obj.name}", reason="ویرایش محصول")
            messages.success(request, f"محصول «{obj.name}» با موفقیت ویرایش شد.")
            return redirect("masterdata:product_list")
    else:
        form = ProductForm(instance=obj)
    return render(request, "masterdata/product_form.html", {"form": form, "title": f"ویرایش محصول «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def product_toggle(request, pk):
    obj = get_object_or_404(Product, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    status_text = "فعال" if obj.is_active else "غیرفعال"
    messages.info(request, f"محصول «{obj.name}» {status_text} شد.")
    return redirect("masterdata:product_list")


# ----------------- Parties (طرف‌های حساب) -----------------
@login_required
def party_list(request):
    parties = Party.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, parties, ["name", "code", "phone", "national_id"])
    return render(request, "masterdata/party_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def party_create(request):
    if request.method == "POST":
        form = PartyForm(request.POST)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.CREATE, "Party", obj.id, f"طرف حساب {obj.name}", reason="تعریف طرف حساب جدید")
            messages.success(request, f"طرف حساب «{obj.name}» با موفقیت ذخیره شد.")
            return redirect("masterdata:party_list")
    else:
        form = PartyForm()
    return render(request, "masterdata/party_form.html", {"form": form, "title": "افزودن طرف حساب جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def party_edit(request, pk):
    obj = get_object_or_404(Party, pk=pk)
    if request.method == "POST":
        form = PartyForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.UPDATE, "Party", obj.id, f"طرف حساب {obj.name}", reason="ویرایش طرف حساب")
            messages.success(request, f"طرف حساب «{obj.name}» با موفقیت ویرایش شد.")
            return redirect("masterdata:party_list")
    else:
        form = PartyForm(instance=obj)
    return render(request, "masterdata/party_form.html", {"form": form, "title": f"ویرایش طرف حساب «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def party_toggle(request, pk):
    obj = get_object_or_404(Party, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    status_text = "فعال" if obj.is_active else "غیرفعال"
    messages.info(request, f"طرف حساب «{obj.name}» {status_text} شد.")
    return redirect("masterdata:party_list")


# ----------------- Drivers (رانندگان) -----------------
@login_required
def driver_list(request):
    drivers = Driver.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, drivers, ["full_name", "mobile", "national_code", "license_number"])
    return render(request, "masterdata/driver_list.html", {"page_obj": page_obj, "q": q})

@login_required
def driver_create(request):
    if request.method == "POST":
        form = DriverForm(request.POST)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.CREATE, "Driver", obj.id, f"راننده {obj.full_name}", reason="ثبت راننده جدید")
            messages.success(request, f"راننده «{obj.full_name}» با موفقیت اضافه شد.")
            return redirect("masterdata:driver_list")
    else:
        form = DriverForm()
    return render(request, "masterdata/driver_form.html", {"form": form, "title": "افزودن راننده جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def driver_edit(request, pk):
    obj = get_object_or_404(Driver, pk=pk)
    if request.method == "POST":
        form = DriverForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.UPDATE, "Driver", obj.id, f"راننده {obj.full_name}", reason="ویرایش راننده")
            messages.success(request, f"راننده «{obj.full_name}» با موفقیت ویرایش شد.")
            return redirect("masterdata:driver_list")
    else:
        form = DriverForm(instance=obj)
    return render(request, "masterdata/driver_form.html", {"form": form, "title": f"ویرایش راننده «{obj.full_name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def driver_toggle(request, pk):
    obj = get_object_or_404(Driver, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    status_text = "فعال" if obj.is_active else "غیرفعال"
    messages.info(request, f"راننده «{obj.full_name}» {status_text} شد.")
    return redirect("masterdata:driver_list")


# ----------------- Vehicles (خودروها) -----------------
@login_required
def vehicle_list(request):
    vehicles = Vehicle.objects.select_related("vehicle_type", "default_driver").all().order_by("-id")
    page_obj, q = paginate_and_search(request, vehicles, ["plate_display", "plate_part1", "plate_part2", "description"])
    return render(request, "masterdata/vehicle_list.html", {
        "page_obj": page_obj,
        "vehicles": page_obj,
        "q": q,
        "title": "مدیریت خودروها و ناوگان حمل و نقل",
    })

@login_required
def vehicle_create(request):
    if request.method == "POST":
        form = VehicleForm(request.POST)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.CREATE, "Vehicle", obj.id, f"خودرو {obj.plate_display}", reason="ثبت خودرو جدید")
            messages.success(request, f"خودرو با پلاک «{obj.plate_display}» با موفقیت ثبت شد.")
            return redirect("masterdata:vehicle_list")
    else:
        form = VehicleForm()
    return render(request, "masterdata/vehicle_form.html", {"form": form, "title": "ثبت خودرو جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def vehicle_edit(request, pk):
    obj = get_object_or_404(Vehicle, pk=pk)
    if request.method == "POST":
        form = VehicleForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            log_audit(AuditAction.UPDATE, "Vehicle", obj.id, f"خودرو {obj.plate_display}", reason="ویرایش خودرو")
            messages.success(request, f"اطلاعات خودرو «{obj.plate_display}» ویرایش شد.")
            return redirect("masterdata:vehicle_list")
    else:
        form = VehicleForm(instance=obj)
    return render(request, "masterdata/vehicle_form.html", {"form": form, "title": f"ویرایش خودرو {obj.plate_display}", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def vehicle_toggle(request, pk):
    obj = get_object_or_404(Vehicle, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    status_text = "فعال" if obj.is_active else "غیرفعال"
    messages.info(request, f"خودرو {obj.plate_display} {status_text} شد.")
    return redirect("masterdata:vehicle_list")


# ----------------- Vehicle Types (انواع خودرو) -----------------
@login_required
def vehicle_type_list(request):
    vtypes = VehicleType.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, vtypes, ["name", "code"])
    return render(request, "masterdata/vehicle_type_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def vehicle_type_create(request):
    if request.method == "POST":
        form = VehicleTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع خودرو «{obj.name}» افزوده شد.")
            return redirect("masterdata:vehicle_type_list")
    else:
        form = VehicleTypeForm()
    return render(request, "masterdata/vehicle_type_form.html", {"form": form, "title": "افزودن نوع خودرو"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def vehicle_type_edit(request, pk):
    obj = get_object_or_404(VehicleType, pk=pk)
    if request.method == "POST":
        form = VehicleTypeForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع خودرو «{obj.name}» ویرایش شد.")
            return redirect("masterdata:vehicle_type_list")
    else:
        form = VehicleTypeForm(instance=obj)
    return render(request, "masterdata/vehicle_type_form.html", {"form": form, "title": f"ویرایش «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def vehicle_type_toggle(request, pk):
    obj = get_object_or_404(VehicleType, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:vehicle_type_list")


# ----------------- Locations (مبادی و مقاصد) -----------------
@login_required
def location_list(request):
    locs = Location.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, locs, ["name", "description"])
    return render(request, "masterdata/location_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def location_create(request):
    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"محل «{obj.name}» ذخیره شد.")
            return redirect("masterdata:location_list")
    else:
        form = LocationForm()
    return render(request, "masterdata/location_form.html", {"form": form, "title": "افزودن محل جدید (مبدأ / مقصد)"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def location_edit(request, pk):
    obj = get_object_or_404(Location, pk=pk)
    if request.method == "POST":
        form = LocationForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"محل «{obj.name}» ویرایش شد.")
            return redirect("masterdata:location_list")
    else:
        form = LocationForm(instance=obj)
    return render(request, "masterdata/location_form.html", {"form": form, "title": f"ویرایش محل «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def location_toggle(request, pk):
    obj = get_object_or_404(Location, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:location_list")


# ----------------- Unload Locations (جایگاه‌های تخلیه) -----------------
@login_required
def unload_location_list(request):
    ulocs = UnloadLocation.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, ulocs, ["name", "code", "description"])
    return render(request, "masterdata/unload_location_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def unload_location_create(request):
    if request.method == "POST":
        form = UnloadLocationForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"جایگاه تخلیه «{obj.name}» افزوده شد.")
            return redirect("masterdata:unload_location_list")
    else:
        form = UnloadLocationForm()
    return render(request, "masterdata/unload_location_form.html", {"form": form, "title": "افزودن جایگاه تخلیه جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def unload_location_edit(request, pk):
    obj = get_object_or_404(UnloadLocation, pk=pk)
    if request.method == "POST":
        form = UnloadLocationForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"جایگاه «{obj.name}» ویرایش شد.")
            return redirect("masterdata:unload_location_list")
    else:
        form = UnloadLocationForm(instance=obj)
    return render(request, "masterdata/unload_location_form.html", {"form": form, "title": f"ویرایش «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def unload_location_toggle(request, pk):
    obj = get_object_or_404(UnloadLocation, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:unload_location_list")


# ----------------- Operation Types -----------------
@login_required
def operation_type_list(request):
    optypes = OperationType.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, optypes, ["name", "code"])
    return render(request, "masterdata/operation_type_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def operation_type_create(request):
    if request.method == "POST":
        form = OperationTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع عملیات «{obj.name}» افزوده شد.")
            return redirect("masterdata:operation_type_list")
    else:
        form = OperationTypeForm()
    return render(request, "masterdata/operation_type_form.html", {"form": form, "title": "افزودن نوع عملیات"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def operation_type_edit(request, pk):
    obj = get_object_or_404(OperationType, pk=pk)
    if request.method == "POST":
        form = OperationTypeForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع عملیات «{obj.name}» ویرایش شد.")
            return redirect("masterdata:operation_type_list")
    else:
        form = OperationTypeForm(instance=obj)
    return render(request, "masterdata/operation_type_form.html", {"form": form, "title": f"ویرایش «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def operation_type_toggle(request, pk):
    obj = get_object_or_404(OperationType, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:operation_type_list")


# ----------------- Loss Types -----------------
@login_required
def loss_type_list(request):
    losses = LossType.objects.all().order_by("-id")
    page_obj, q = paginate_and_search(request, losses, ["name", "code", "description"])
    return render(request, "masterdata/loss_type_list.html", {"page_obj": page_obj, "q": q})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def loss_type_create(request):
    if request.method == "POST":
        form = LossTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع افت «{obj.name}» افزوده شد.")
            return redirect("masterdata:loss_type_list")
    else:
        form = LossTypeForm()
    return render(request, "masterdata/loss_type_form.html", {"form": form, "title": "افزودن نوع افت جدید"})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
def loss_type_edit(request, pk):
    obj = get_object_or_404(LossType, pk=pk)
    if request.method == "POST":
        form = LossTypeForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"نوع افت «{obj.name}» ویرایش شد.")
            return redirect("masterdata:loss_type_list")
    else:
        form = LossTypeForm(instance=obj)
    return render(request, "masterdata/loss_type_form.html", {"form": form, "title": f"ویرایش نوع افت «{obj.name}»", "object": obj})

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager")
@require_POST
def loss_type_toggle(request, pk):
    obj = get_object_or_404(LossType, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:loss_type_list")


# ----------------- AJAX Quick Add Endpoints for Ticket Form -----------------
def normalize_search_text(val):
    if not val:
        return ""
    val = str(val).strip().replace("ي", "ی").replace("ك", "ک")
    return " ".join(val.split())

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def api_quick_add(request, entity=None):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "متد غیرمجاز است."}, status=405)

    if not entity:
        entity = request.POST.get("entity", "").strip()

    name = request.POST.get("name", "").strip()
    norm_name = normalize_search_text(name)

    if not name:
        return JsonResponse({"status": "error", "message": "وارد کردن عنوان یا نام الزامی است."}, status=400)

    try:
        if entity == "party":
            party_type = request.POST.get("party_type", PartyType.CUSTOMER)
            phone = request.POST.get("phone", "").strip()
            code = request.POST.get("code", "").strip()
            
            existing = None
            if code:
                existing = Party.objects.filter(code__iexact=code).first()
            if not existing:
                for p in Party.objects.all():
                    if normalize_search_text(p.name) == norm_name:
                        existing = p
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"طرف حساب با نام «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            party = Party.objects.create(
                name=name,
                party_type=party_type,
                phone=phone,
                code=code or None,
                is_active=True
            )
            log_audit(AuditAction.CREATE, "Party", party.id, f"طرف حساب {party.name}", reason="افزودن سریع طرف حساب در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": party.id,
                "text": str(party),
                "name": party.name,
                "message": f"طرف حساب «{party.name}» با موفقیت ثبت و انتخاب شد."
            })

        elif entity == "product":
            code = request.POST.get("code", "").strip()
            default_loss = request.POST.get("default_loss_percent") or "0.00"
            tolerance = request.POST.get("standard_tolerance_kg") or "50.00"

            existing = None
            if code:
                existing = Product.objects.filter(code__iexact=code).first()
            if not existing:
                for pr in Product.objects.all():
                    if normalize_search_text(pr.name) == norm_name:
                        existing = pr
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"محصول با نام «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            try:
                loss_dec = Decimal(str(default_loss))
            except Exception:
                loss_dec = Decimal("0.00")
            try:
                tol_dec = Decimal(str(tolerance))
            except Exception:
                tol_dec = Decimal("50.00")

            product = Product.objects.create(
                name=name,
                code=code or None,
                default_loss_percent=loss_dec,
                standard_tolerance_kg=tol_dec,
                is_active=True
            )
            log_audit(AuditAction.CREATE, "Product", product.id, f"محصول {product.name}", reason="افزودن سریع محصول در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": product.id,
                "text": str(product),
                "name": product.name,
                "message": f"محصول «{product.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "operation_type":
            direction = request.POST.get("direction", OperationDirection.INBOUND)
            code = request.POST.get("code", "").strip()

            existing = None
            if code:
                existing = OperationType.objects.filter(code__iexact=code).first()
            if not existing:
                for op in OperationType.objects.all():
                    if normalize_search_text(op.name) == norm_name:
                        existing = op
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"نوع عملیات «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            op = OperationType.objects.create(name=name, direction=direction, code=code or None, is_active=True)
            log_audit(AuditAction.CREATE, "OperationType", op.id, f"نوع عملیات {op.name}", reason="افزودن سریع نوع عملیات در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": op.id,
                "text": str(op),
                "name": op.name,
                "message": f"نوع عملیات «{op.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "vehicle_type":
            tare = request.POST.get("standard_tare_weight") or "0.00"
            code = request.POST.get("code", "").strip()

            existing = None
            if code:
                existing = VehicleType.objects.filter(code__iexact=code).first()
            if not existing:
                for vt in VehicleType.objects.all():
                    if normalize_search_text(vt.name) == norm_name:
                        existing = vt
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"نوع خودرو «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            try:
                tare_dec = Decimal(str(tare))
            except Exception:
                tare_dec = Decimal("0.00")

            vt = VehicleType.objects.create(name=name, standard_tare_weight=tare_dec, code=code or None, is_active=True)
            log_audit(AuditAction.CREATE, "VehicleType", vt.id, f"نوع خودرو {vt.name}", reason="افزودن سریع نوع خودرو در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": vt.id,
                "text": str(vt),
                "name": vt.name,
                "message": f"نوع خودرو «{vt.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity in ("origin", "destination", "location"):
            desc = request.POST.get("description", "").strip()
            existing = None
            for loc in Location.objects.all():
                if normalize_search_text(loc.name) == norm_name:
                    existing = loc
                    break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                if entity == "origin" and existing.location_type == LocationType.DESTINATION:
                    existing.location_type = LocationType.BOTH
                elif entity == "destination" and existing.location_type == LocationType.ORIGIN:
                    existing.location_type = LocationType.BOTH
                existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"محل «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            loc = Location.objects.create(name=name, location_type=LocationType.BOTH, description=desc, is_active=True)
            log_audit(AuditAction.CREATE, "Location", loc.id, f"محل {loc.name}", reason="افزودن سریع مبدأ/مقصد در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": loc.id,
                "text": str(loc),
                "name": loc.name,
                "message": f"محل «{loc.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "unload_location":
            code = request.POST.get("code", "").strip()
            desc = request.POST.get("description", "").strip()

            existing = None
            if code:
                existing = UnloadLocation.objects.filter(code__iexact=code).first()
            if not existing:
                for ul in UnloadLocation.objects.all():
                    if normalize_search_text(ul.name) == norm_name:
                        existing = ul
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"جایگاه «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            ul = UnloadLocation.objects.create(name=name, code=code or None, description=desc, is_active=True)
            log_audit(AuditAction.CREATE, "UnloadLocation", ul.id, f"جایگاه تخلیه {ul.name}", reason="افزودن سریع جایگاه تخلیه در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": ul.id,
                "text": str(ul),
                "name": ul.name,
                "message": f"جایگاه «{ul.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "loss_type":
            code = request.POST.get("code", "").strip()
            default_pct = request.POST.get("default_percent") or "0.00"
            desc = request.POST.get("description", "").strip()

            existing = None
            if code:
                existing = LossType.objects.filter(code__iexact=code).first()
            if not existing:
                for lt in LossType.objects.all():
                    if normalize_search_text(lt.name) == norm_name:
                        existing = lt
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.name,
                    "message": f"نوع افت «{existing.name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            try:
                pct_dec = Decimal(str(default_pct))
            except Exception:
                pct_dec = Decimal("0.00")

            lt = LossType.objects.create(name=name, code=code or None, default_percent=pct_dec, description=desc, is_active=True)
            log_audit(AuditAction.CREATE, "LossType", lt.id, f"نوع افت {lt.name}", reason="افزودن سریع نوع افت در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": lt.id,
                "text": str(lt),
                "name": lt.name,
                "message": f"نوع افت «{lt.name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "driver":
            mobile = request.POST.get("mobile", "").strip()
            nat_code = request.POST.get("national_code", "").strip()
            existing = None
            if nat_code:
                existing = Driver.objects.filter(national_code=nat_code).first()
            if not existing and mobile:
                existing = Driver.objects.filter(mobile=mobile).first()
            if not existing:
                for d in Driver.objects.all():
                    if normalize_search_text(d.full_name) == norm_name:
                        existing = d
                        break

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "name": existing.full_name,
                    "mobile": existing.mobile,
                    "message": f"راننده «{existing.full_name}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            driver = Driver.objects.create(full_name=name, mobile=mobile, national_code=nat_code, is_active=True)
            log_audit(AuditAction.CREATE, "Driver", driver.id, f"راننده {driver.full_name}", reason="افزودن سریع راننده در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": driver.id,
                "text": str(driver),
                "name": driver.full_name,
                "mobile": driver.mobile,
                "message": f"راننده «{driver.full_name}» با موفقیت افزوده و انتخاب شد."
            })

        elif entity == "vehicle":
            p1 = request.POST.get("plate_part1", "").strip()
            pL = request.POST.get("plate_letter", "").strip()
            p2 = request.POST.get("plate_part2", "").strip()
            pIran = request.POST.get("plate_iran", "").strip()
            vtype_id = request.POST.get("vehicle_type")
            display = f"{p1} {pL} {p2} - ایران {pIran}" if (p1 and pL and p2 and pIran) else request.POST.get("plate_display", "").strip() or name

            existing = Vehicle.objects.filter(plate_display=display).first()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                return JsonResponse({
                    "status": "duplicate",
                    "id": existing.id,
                    "text": str(existing),
                    "plate_display": existing.plate_display,
                    "message": f"خودرو با پلاک «{existing.plate_display}» از قبل در سیستم وجود دارد و همان مورد انتخاب گردید."
                })

            vehicle = Vehicle.objects.create(
                plate_part1=p1, plate_letter=pL, plate_part2=p2, plate_iran=pIran,
                plate_display=display, vehicle_type_id=vtype_id if vtype_id else None,
                is_active=True
            )
            log_audit(AuditAction.CREATE, "Vehicle", vehicle.id, f"خودرو {vehicle.plate_display}", reason="افزودن سریع خودرو در فرم قبض")
            return JsonResponse({
                "status": "created",
                "id": vehicle.id,
                "text": str(vehicle),
                "plate_display": vehicle.plate_display,
                "message": f"خودرو «{vehicle.plate_display}» با موفقیت افزوده و انتخاب شد."
            })

        else:
            return JsonResponse({"status": "error", "message": f"موجودیت «{entity}» معتبر نمی‌باشد."}, status=400)

    except Exception as exc:
        return JsonResponse({"status": "error", "message": f"خطا در ثبت اطلاعات: {str(exc)}"}, status=500)

# Legacy aliases
def api_quick_add_party(request):
    return api_quick_add(request, entity="party")

def api_quick_add_driver(request):
    return api_quick_add(request, entity="driver")

def api_quick_add_vehicle(request):
    return api_quick_add(request, entity="vehicle")

def api_quick_add_product(request):
    return api_quick_add(request, entity="product")

