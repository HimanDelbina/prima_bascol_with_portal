from django.db import migrations, models


def backfill_and_verify_collisions(apps, schema_editor):
    from collections import defaultdict
    from weighbridge.plate_policy import normalize_plate

    Vehicle = apps.get_model('masterdata', 'Vehicle')
    db_alias = schema_editor.connection.alias

    # 1. Backfill all vehicles
    vehicles = list(Vehicle.objects.using(db_alias).all())
    plate_groups = defaultdict(list)

    for v in vehicles:
        norm = normalize_plate(v.plate_display)
        v.normalized_plate = norm
        Vehicle.objects.using(db_alias).filter(pk=v.pk).update(normalized_plate=norm)
        if norm:
            plate_groups[norm].append(v.pk)

    # 2. Check for collisions
    collisions = {norm: pks for norm, pks in plate_groups.items() if len(pks) > 1}
    if collisions:
        raise RuntimeError(
            f"MIGRATION HALTED: Detected {len(collisions)} unresolved vehicle plate collision(s) "
            f"before enforcing uniqueness constraint: {dict(collisions)}. "
            f"Per safety requirements, collisions must not be deleted or merged automatically. "
            f"Please run 'python manage.py inspect_plate_collisions' and resolve collisions before migrating."
        )


class Migration(migrations.Migration):

    dependencies = [
        ('masterdata', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='normalized_plate',
            field=models.CharField(blank=True, db_index=True, default='', max_length=60, verbose_name='پلاک استانداردسازی\u200cشده'),
        ),
        migrations.AddIndex(
            model_name='vehicle',
            index=models.Index(fields=['normalized_plate'], name='idx_vehicle_norm_plate'),
        ),
        migrations.AddIndex(
            model_name='vehicle',
            index=models.Index(fields=['plate_display'], name='idx_vehicle_plate_disp'),
        ),
        migrations.RunPython(
            backfill_and_verify_collisions,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='vehicle',
            constraint=models.UniqueConstraint(condition=models.Q(('normalized_plate', ''), _negated=True), fields=('normalized_plate',), name='unique_vehicle_normalized_plate'),
        ),
    ]

