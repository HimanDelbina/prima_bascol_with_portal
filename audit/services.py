from core.middleware import get_current_user, get_current_ip
from audit.models import AuditLog, AuditAction

def log_audit(
    action: str,
    model_name: str,
    record_id: any,
    record_repr: str,
    old_values: dict = None,
    new_values: dict = None,
    reason: str = "",
    user = None,
    ip_address: str = None,
    source: str = "API"
):
    """Utility to register an audit log entry."""
    current_user = user or get_current_user()
    current_ip = ip_address or get_current_ip()
    
    return AuditLog.objects.create(
        user=current_user,
        ip_address=current_ip,
        action=action,
        model_name=model_name,
        record_id=str(record_id),
        record_repr=record_repr,
        old_values=old_values or {},
        new_values=new_values or {},
        reason=reason or "",
        source=source
    )
