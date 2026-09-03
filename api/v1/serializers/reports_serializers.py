from rest_framework import serializers


class ReportSummarySerializer(serializers.Serializer):
    total_tickets = serializers.IntegerField()
    total_loads = serializers.IntegerField()
    sum_gross = serializers.DecimalField(max_digits=14, decimal_places=2)
    sum_tare = serializers.DecimalField(max_digits=14, decimal_places=2)
    sum_net = serializers.DecimalField(max_digits=14, decimal_places=2)
    sum_sent = serializers.DecimalField(max_digits=14, decimal_places=2)
    sum_loss = serializers.DecimalField(max_digits=14, decimal_places=2)
    sum_final = serializers.DecimalField(max_digits=14, decimal_places=2)
    avg_net = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_loss_percent = serializers.DecimalField(max_digits=6, decimal_places=2)
    min_net = serializers.DecimalField(max_digits=12, decimal_places=2)
    max_net = serializers.DecimalField(max_digits=12, decimal_places=2)


class GroupedReportItemSerializer(serializers.Serializer):
    group_title = serializers.CharField()
    item = serializers.DictField()
