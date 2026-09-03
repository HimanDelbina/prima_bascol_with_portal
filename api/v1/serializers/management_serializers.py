from rest_framework import serializers


class MetricComparisonSerializer(serializers.Serializer):
    current = serializers.FloatField()
    previous = serializers.FloatField()
    diff = serializers.FloatField()
    pct_change = serializers.FloatField()
    is_positive = serializers.BooleanField()
    is_neutral = serializers.BooleanField()


class ManagementSummarySerializer(serializers.Serializer):
    period_label = serializers.CharField()
    start_date_jalali = serializers.CharField()
    end_date_jalali = serializers.CharField()
    narrative = serializers.CharField()
    kpis = serializers.DictField()
    comparison = serializers.DictField()
