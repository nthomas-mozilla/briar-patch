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
def calculate_pricing(usage, ondemand_hourly, res_pricing, res_count,
                      perTerm=False):

    res_upfront_spread = res_pricing['upfront'] / res_pricing['term'] * res_count

    # break out the 'fixed' cost of always getting charged for high utilization
    # res. instances, vs the actual usage cost
    res_fixed = 0
    res_hourly = 0
    if res_pricing.get('always_hourly', False):
        res_fixed = res_pricing['hourly'] * one_month * res_count
    else:
        for instance_count in range(0,res_count+1):
            res_hourly += res_pricing['hourly'] * instance_count * usage[instance_count]

    # residual usage at ondemand
    ondemand = 0
    for instance_count in range(res_count+1, len(usage)):
        ondemand += ondemand_hourly * (instance_count - res_count) * usage[instance_count]

    total =  res_upfront_spread + res_fixed + res_hourly + ondemand
    price_parts = [total, res_upfront_spread, res_fixed, res_hourly, ondemand]
    if perTerm:
        price_parts = [p * res_pricing['term'] for p in price_parts]

    return price_parts

# loop over a range of possible reserved instances to find the lowest cost
def minimize_pricing(usage, ondemand_hourly, res_pricing, res_range, textReport=False):

    prices = []
    for res_count in res_range:
        prices.append(calculate_pricing(usage, ondemand_hourly, res_pricing, res_count)[0])

    if textReport:
        # assume a global minimum, might fall over if the distribution shape is odd
        res_best = prices.index(min(prices))
        best_pricing = calculate_pricing(usage, ondemand_hourly, res_pricing, res_best)
        if res_best == 0:
            print "%15s: cheaper to use ondemand" % res_pricing['name']
        else:
            saving_month = prices[0] - prices[res_best]
            print "%15s: best saving at %2s instances - $%6.0f upfront, $%8.2f fixed/month, $%8.2f saved/month, $%7.0f over term" % (
                res_pricing['name'], res_best, best_pricing[1],
                best_pricing[2], saving_month, res_pricing['term'] * saving_month)

    return prices


# pricing for Linux '* Utilization Reserved Instances' of type
#                   'High-CPU On-Demand Instances' (aka c1.xlarge) in
#                   'US West (Northen California)' (aka USW1)
# NB, Heavy Utilisation Reserved Instances are always charged the hourly fee
#   see http://aws.amazon.com/ec2/reserved-instances/#5
# we get charged 0.72 for on demand now but pricing page says 0.744, ok!
# we neglect other components like IOps and transfer since instance are our biggest cost

one_month = 365.25/12 * 24 # hours / month
ondemand_hourly = 0.72    # $/hour
reserved_pricing = [
    {
        'name': 'light-1yr',
        'upfront': 712.,  # $
        'hourly': 0.50,  # $/hour
        'term': 12,      # months
    },
    {
        'name': 'light-3yr',
        'upfront': 1092., # $
        'hourly': 0.44,  # $/hour
        'term' : 36,     # months
    },
    {
        'name': 'medium-1yr',
        'upfront': 1660., # $
        'hourly': 0.32,  # $/hour
        'term': 12,      # months
     },
    {
        'name': 'medium-3yr',
        'upfront': 2552., # $
        'hourly': 0.28,  # $/hour
        'term': 36,      # months
     },
    {
        'name': 'high-1yr',
        'upfront': 2000., # $
        'hourly': 0.25,  # $/hour
        'term': 12,      # months
        'always_hourly': True,    # High Utilisation charges all hours reqardless of use
     },
    {
        'name': 'high-3yr',
        'upfront': 3100., # $
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
                minimize_pricing(counts, ondemand_hourly, {'name': 'ondemand', 'hourly': ondemand_hourly, 'term': 1, 'upfront': 0}, [0], textReport=False)[0],
                max(reserved_range))

    # calculate the costs
    prices = []
    for p in reserved_pricing:
        prices.append(
            {
                'name': p['name'],
                'pricing': minimize_pricing(counts, ondemand_hourly, p,
                                             reserved_range, textReport=True),
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

