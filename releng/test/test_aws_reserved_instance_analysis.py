import unittest

from aws_reserved_instance_analysis import calculate_pricing

class TestBillingCalculation(unittest.TestCase):
    ondemand_hourly = 0.80
    pricing = [
            {
            'name': 'simple',
            'upfront': 1200., # $
            'hourly': 0.5,  # $/hour
            'term': 12,      # months
        },
        {
            'name': 'high',
            'upfront': 1800., # $
            'hourly': 0.25,  # $/hour
            'term': 12,      # months
            'always_hourly': True,    # High Utilisation charges all hours reqardless of use
        }, 
    ]

#[total, res_upfront_spread, res_fixed, res_hourly, ondemand]
    def testOnDemandTrivial(self):
        # 1 count of 1 ondemand instance
        price = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[0], 0)
        self.assertEqual(price, [0.80, 0, 0, 0, 0.80])

    def testOnDemandDistribution(self):
        # a more complicated example, a decaying distribution with 20 instances total
        price = calculate_pricing([5,4,3,2,1], self.ondemand_hourly, self.pricing[0], 0)
        self.assertEqual(price, [16.0, 0, 0, 0, 16.0])

    def testReservedSimpleTrivial(self):
        # 1 count of usage, 1 reserved instance
        price = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[0], 1)
        self.assertEqual(price, [100.5, 100, 0, 0.5, 0])

    def testReservedSimpleDistribution(self):
        # a more complicated example, some reserved & some ondemand usage
        price = calculate_pricing([3,2,1], self.ondemand_hourly, self.pricing[0], 1)
        self.assertEqual(price, [101.8, 100, 0, 1.0, 0.8])

    def testReservedHighTrivial(self):
        # 1 count of usage, 1 reserved high-utilization instance
        price = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[1], 1)
        self.assertEqual(price, [332.625, 150, 182.625, 0, 0])

    def testReservedHighDistribution(self):
        # a more complicated high-util example, some reserved & ondemand usage
        price = calculate_pricing([3,2,1], self.ondemand_hourly, self.pricing[1], 1)
        self.assertEqual(price, [333.425, 150, 182.625, 0, 0.8])

    def testReservedSimpleMultiple(self):
        # 1 count of usage, 2 reserved instances
        price = calculate_pricing([0,1,0], self.ondemand_hourly, self.pricing[0], 2)
        self.assertEqual(price, [200.5, 200, 0, 0.5, 0])

    def testReservedSimpleFullTerm(self):
        # 1 count of usage, 2 reserved instances
        price = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[0], 1,
                                  perTerm=True)
        self.assertEqual(price, [1206, 1200, 0, 6.0, 0])
