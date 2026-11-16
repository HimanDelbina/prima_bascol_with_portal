from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_alter_userprofile_role"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="BascolIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("issuer", models.URLField(max_length=255)),
                ("subject", models.CharField(max_length=255)),
                ("enabled", models.BooleanField(default=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                    related_name="bascol_identity", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "پیوند حساب سازمانی",
                "verbose_name_plural": "پیوندهای حساب سازمانی",
                "constraints": [models.UniqueConstraint(fields=["issuer", "subject"], name="bascol_oidc_identity_unique")],
            },
        ),
    ]
