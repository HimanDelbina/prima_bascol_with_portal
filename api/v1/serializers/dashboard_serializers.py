from rest_framework import serializers


class DashboardSummarySerializer(serializers.Serializer):
    today_ticket_count = serializers.IntegerField()
    today_completed_count = serializers.IntegerField()
    today_net_weight = serializers.DecimalField(max_digits=12, decimal_places=2)
    today_tonnage = serializers.FloatField()
    today_inbound_weight = serializers.DecimalField(max_digits=12, decimal_places=2)
    today_outbound_weight = serializers.DecimalField(max_digits=12, decimal_places=2)
    waiting_second_weight = serializers.IntegerField()
    today_discrepancies = serializers.IntegerField()
    open_alerts_count = serializers.IntegerField()
    today_critical_alerts = serializers.IntegerField()


class DashboardTrendSerializer(serializers.Serializer):
    dates_30 = serializers.ListField(child=serializers.CharField())
    tonnage_30 = serializers.ListField(child=serializers.FloatField())
    trips_30 = serializers.ListField(child=serializers.IntegerField())
    product_labels = serializers.ListField(child=serializers.CharField())
    product_values = serializers.ListField(child=serializers.FloatField())
    inbound_tonnage = serializers.FloatField()
    outbound_tonnage = serializers.FloatField()
    party_labels = serializers.ListField(child=serializers.CharField())
    party_values = serializers.ListField(child=serializers.FloatField())
