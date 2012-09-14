import unittest

from aws_reserved_instance_analysis import calculate_pricing

class TestBillingCalculation(unittest.TestCase):
    ondemand_hourly = 0.80
    pricing = [
            {
            'name': 'simple',
            'upfront': 100., # $
            'hourly': 0.5,  # $/hour
            'term': 12,      # months
        },
        {
            'name': 'high',
            'upfront': 200., # $
            'hourly': 0.25,  # $/hour
            'term': 12,      # months
            'always_hourly': True,    # High Utilisation charges all hours reqardless of use
        }, 
    ]
    one_month = 365.25/12 * 24 # hours / month

    def testOnDemandTrivial(self):
        # 1 count of 1 ondemand instance
        prices = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[0], [0])
        self.assertEqual(prices[0], self.ondemand_hourly)

    def testOnDemandDistribution(self):
        # a more complicated example, a decaying distribution
        prices = calculate_pricing([5,4,3,2,1], self.ondemand_hourly, self.pricing[0], [0])
        self.assertEqual(prices[0], self.ondemand_hourly*20)

    def testReservedSimpleTrivial(self):
        # 1 count of usage 1 reserved instance
        prices = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[0], [1])
        expected = self.pricing[0]['upfront'] / self.pricing[0]['term'] + \
                     self.pricing[0]['hourly']
        self.assertEqual(prices[0], expected)

    def testReservedSimpleDistribution(self):
        # a more complicated example, some reserved some ondemand usage
        prices = calculate_pricing([3,2,1], self.ondemand_hourly, self.pricing[0], [1])
        expected = self.pricing[0]['upfront'] / self.pricing[0]['term'] + \
                     self.pricing[0]['hourly']*2 + self.ondemand_hourly
        self.assertEqual(prices[0], expected)

    def testReservedHighTrivial(self):
        # 1 count of usage 1 reserved instance
        prices = calculate_pricing([0,1], self.ondemand_hourly, self.pricing[1], [1])
        expected = self.pricing[1]['upfront'] / self.pricing[1]['term'] + \
                     self.pricing[1]['hourly'] * self.one_month
        self.assertEqual(prices[0], expected)

    def testReservedHighDistribution(self):
        # a more complicated example, some reserved some ondemand usage
        prices = calculate_pricing([3,2,1], self.ondemand_hourly, self.pricing[1], [1])
        expected = self.pricing[1]['upfront'] / self.pricing[1]['term'] + \
                     self.pricing[1]['hourly'] * self.one_month + \
                     self.ondemand_hourly
        self.assertEqual(prices[0], expected)