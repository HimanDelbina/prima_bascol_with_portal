from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle, 
    Location, UnloadLocation, OperationType, LossType
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
    return render(request, "masterdata/product_list.html", {"page_obj": page_obj, "q": q})

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
    return render(request, "masterdata/vehicle_list.html", {"page_obj": page_obj, "q": q})

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
def loss_type_toggle(request, pk):
    obj = get_object_or_404(LossType, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    return redirect("masterdata:loss_type_list")


# ----------------- AJAX Quick Add Endpoints for Ticket Form -----------------
@login_required
def api_quick_add_party(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        party_type = request.POST.get("party_type", "customer")
        phone = request.POST.get("phone", "").strip()
        if name:
            party = Party.objects.create(name=name, party_type=party_type, phone=phone)
            return JsonResponse({"status": "success", "id": party.id, "name": str(party)})
    return JsonResponse({"status": "error", "message": "نام طرف حساب الزامی است."}, status=400)

@login_required
def api_quick_add_driver(request):
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        mobile = request.POST.get("mobile", "").strip()
        national_code = request.POST.get("national_code", "").strip()
        if full_name:
            driver = Driver.objects.create(full_name=full_name, mobile=mobile, national_code=national_code)
            return JsonResponse({"status": "success", "id": driver.id, "name": str(driver), "mobile": mobile})
    return JsonResponse({"status": "error", "message": "نام راننده الزامی است."}, status=400)

@login_required
def api_quick_add_vehicle(request):
    if request.method == "POST":
        p1 = request.POST.get("plate_part1", "").strip()
        pL = request.POST.get("plate_letter", "").strip()
        p2 = request.POST.get("plate_part2", "").strip()
        pIran = request.POST.get("plate_iran", "").strip()
        vtype_id = request.POST.get("vehicle_type")
        
        display = f"{p1} {pL} {p2} - ایران {pIran}" if (p1 and pL and p2 and pIran) else request.POST.get("plate_display", "").strip()
        if display:
            vehicle = Vehicle.objects.create(
                plate_part1=p1, plate_letter=pL, plate_part2=p2, plate_iran=pIran,
                plate_display=display, vehicle_type_id=vtype_id if vtype_id else None
            )
            return JsonResponse({"status": "success", "id": vehicle.id, "plate_display": vehicle.plate_display})
    return JsonResponse({"status": "error", "message": "اطلاعات پلاک خودرو ناقص است."}, status=400)

@login_required
def api_quick_add_product(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        code = request.POST.get("code", "").strip()
        if name:
            prod = Product.objects.create(name=name, code=code)
            return JsonResponse({"status": "success", "id": prod.id, "name": str(prod)})
    return JsonResponse({"status": "error", "message": "نام محصول الزامی است."}, status=400)
