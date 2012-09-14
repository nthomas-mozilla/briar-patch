import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import datetime
import json

# read the data from Amazon billing
def retrieve_usage_data(startWindow, endWindow):
    from aws_retrieve_billing_data import get_report

    secrets = json.load(open('portal_secrets'))
    username = secrets['portal_username']
    password = secrets['portal_password']

    counts = {}

    response = get_report('AmazonEC2', startWindow, endWindow + datetime.timedelta(days=1),
                          username, password, format='csv', period='hours')
    f = open('usage-reports/instance-run_c1.xlarge.csv','w')
    for d in response.splitlines(True):
        if 'RunInstances,USW1-BoxUsage:c1.xlarge' in d:
            f.write(d)
    f.close()

# generalised billing model
def calculate_pricing(usage, pricing, reserved_range, textReport=True):
    prices = []
    one_month         = 365.25/12 * 24 # hours / month

    for r_count in reserved_range:
        r_price = pricing['upfront']/pricing['term'] * r_count
        if pricing.get('always_hourly', False):
            r_price += pricing['hourly'] * one_month * r_count
        else:
            for i in range(0,r_count+1):
                r_price += pricing['hourly'] * i * counts[i]
        for i in range(r_count+1, len(counts)):
            r_price += ondemand_instance_hourly * (i - r_count) * counts[i]
        prices.append(r_price)

    if textReport:
        reserved_best = prices.index(min(prices))
        if reserved_best == 0:
            print "%15s: cheaper to use ondemand" % pricing['name']
        else:
            saving_month = prices[0] - prices[reserved_best]
            if pricing.get('always_hourly', False):
                fixed_month = pricing['hourly'] * one_month * reserved_best
            else:
                fixed_month = 0
            print "%15s: best saving at %2s instances - $%6.0f upfront, $%8.2f fixed/month, $%8.2f saved/month, $%7.0f over term" % (
                pricing['name'], reserved_best, reserved_best * pricing['upfront'],
                fixed_month, saving_month, pricing['term'] * saving_month)
        #for i in range(0,len(prices)):
        #    print "%5s %-8.2f" % (i, prices[i])

    return prices


# pricing for Linux '* Utilization Reserved Instances' of type
#                   'High-CPU On-Demand Instances' (aka c1.xlarge) in
#                   'US West (Northen California)' (aka USW1)
# NB, Heavy Utilisation Reserved Instances are always charged the hourly fee
#   see http://aws.amazon.com/ec2/reserved-instances/#5
# we get charged 0.72 for on demand now but pricing page says 0.744, ok!
# we neglect other components like IOps and transfer since instance are our biggest cost

ondemand_instance_hourly = 0.72    # $/hour
reserved_pricing = [
    {
        'name': 'light-1yr',
        'upfront': 712,  # $
        'hourly': 0.50,  # $/hour
        'term': 12,      # months
    },
    {
        'name': 'light-3yr',
        'upfront': 1092, # $
        'hourly': 0.44,  # $/hour
        'term' : 36,     # months
    },
    {
        'name': 'medium-1yr',
        'upfront': 1660, # $
        'hourly': 0.32,  # $/hour
        'term': 12,      # months
     },
    {
        'name': 'medium-3yr',
        'upfront': 2552, # $
        'hourly': 0.28,  # $/hour
        'term': 36,      # months
     },
    {
        'name': 'high-1yr',
        'upfront': 2000, # $
        'hourly': 0.25,  # $/hour
        'term': 12,      # months
        'always_hourly': True,    # High Utilisation charges all hours reqardless of use
     },
    {
        'name': 'high-3yr',
        'upfront': 3100, # $
        'hourly': 0.22,  # $/hour
        'term': 36,      # months
        'always_hourly': True,    # High Utilisation charges all hours reqardless of use
     },
]


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-n", "--no-retrieve", dest="retrieve_data", action="store_false",
                      help="Don't ask Amazon for billing data", default=True)
    options, args = parser.parse_args()

    california = pytz.timezone('US/Pacific')
    utc = pytz.utc

    endWindow = datetime.datetime.now(tz=utc).replace(minute=0, second=0, microsecond=0)
    startWindow = endWindow - datetime.timedelta(days=31)

    if options.retrieve_data:
        retrieve_usage_data(startWindow, endWindow)

    # load data, this returns numpy.array's
    # any 0 instance hours are ommitted by Amazon in the log, so our hist is off for that
    times, raw_counts = np.loadtxt("usage-reports/instance-run_c1.xlarge.csv",
            unpack=True, delimiter=',', usecols=(4,6),
            converters={ 4: mdates.strpdate2num('%m/%d/%y %H:%M:%S')})

    # convert to a list where the index is the instance usage, value is frequency
    # diy histogram
    counts = np.zeros(max(raw_counts)+1)
    for r in raw_counts:
       counts[r] += 1

    # our range of interest for reserved slaves
    # must include 0 to correctly calculate savings
    reserved_range = range(0, min(len(counts), 31))
    print "%15s: $%1.2f/month, considering up to %s reserved instances ..." % ('ondemand',
                calculate_pricing(counts, {'name': 'ondemand', 'hourly': ondemand_instance_hourly, 'term': 1, 'upfront': 0}, [0], textReport=False)[0],
                max(reserved_range))

    # calculate the costs
    prices = []
    for p in reserved_pricing:
        prices.append(
            {
                'name': p['name'],
                'pricing': calculate_pricing(counts, p, reserved_range),
            }
        )

    # create a plot for last month
    fig = plt.figure()
    ax = fig.gca()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%H%M', tz=california))

    width=1.0/24
    plt.bar(times, raw_counts, width=width, color='c', align='center', label='Amazon Billing', linewidth=0)
    plt.xlabel('Pacific time')
    plt.ylabel('Instances Used')
    plt.grid(True)
    ax.set_xlim((startWindow, endWindow))

    plt.savefig('usage-reports/instance_month.png')

    # create a histogram plot for instance usage
    fig = plt.figure()
    ax = fig.gca()

    plt.hist(raw_counts, range(0,81), color= 'r', align='left')
    plt.xlabel('Instances used per hour')
    plt.ylabel('Frequency')
    plt.title('Instance usage in the %s from %s' % (endWindow - startWindow, endWindow))
    plt.grid(True)

    plt.savefig('usage-reports/instance_histogram.png')

    ##############################################################################################
    # create a plot for reserved instance_pricing

    fig = plt.figure()
    ax = fig.gca()

    for p in prices:
      plt.plot(reserved_range, p['pricing'], 'x-', label=p['name'])
    plt.xlabel('Number of reserved instances')
    plt.ylabel('Monthly cost')
    plt.title('Reserved instance cost calculation')
    plt.grid(True)
    plt.legend()

    plt.savefig('usage-reports/instance_costing.png')

