from myelin.pricers.ipsf import IPSFProvider


class FakeClient:
    def java_big_decimal_class(self, value):
        return value

    def java_integer_class(self, value):
        return value

    def py_date_to_java_date(self, value):
        return value


class FakeJavaProvider:
    def __init__(self):
        self.calls = {}

    def __getattr__(self, name):
        if name.startswith("set"):

            def setter(value):
                self.calls[name] = value

            return setter
        raise AttributeError(name)


def test_ipsf_provider_does_not_set_supplemental_wage_index_by_default():
    provider = IPSFProvider(
        supplemental_wage_index=1.2345,
        supplemental_wage_index_indicator="2",
    )
    java_provider = FakeJavaProvider()

    provider.set_java_values(java_provider, FakeClient())

    assert "setSupplementalWageIndex" not in java_provider.calls
    assert "setSupplementalWageIndexIndicator" not in java_provider.calls


def test_ipsf_provider_sets_supplemental_wage_index_when_requested():
    provider = IPSFProvider(
        supplemental_wage_index=1.2345,
        supplemental_wage_index_indicator="2",
    )
    java_provider = FakeJavaProvider()

    provider.set_java_values(
        java_provider,
        FakeClient(),
        include_supplemental_wage_index=True,
    )

    assert java_provider.calls["setSupplementalWageIndex"] == 1.2345
    assert java_provider.calls["setSupplementalWageIndexIndicator"] == "2"
