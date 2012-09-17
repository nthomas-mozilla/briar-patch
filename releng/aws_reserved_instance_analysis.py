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
    price_parts = np.array([total, res_upfront_spread, res_fixed, res_hourly, ondemand])
    if perTerm:
        price_parts = price_parts * res_pricing['term']

    return price_parts

def minimize_pricing(usage, ondemand_hourly, res_pricing, res_range, textReport=False):
    # loop over a range of possible reserved instances to find the lowest cost
    # return a list of total costs, and the reserved instance count to minimize

    prices = []
    for res_count in res_range:
        prices.append(calculate_pricing(usage, ondemand_hourly, res_pricing, res_count)[0])

    # assume a global minimum, might fall over if the distribution shape is odd
    res_best = prices.index(min(prices))
    best_pricing = calculate_pricing(usage, ondemand_hourly, res_pricing, res_best)

    if textReport:
        if res_best == 0:
            print "%15s: cheaper to use ondemand" % res_pricing['name']
        else:
            saving_month = prices[0] - prices[res_best]
            print "%15s: best saving at %2s instances - $%6.0f upfront, $%8.2f fixed/month, $%8.2f saved/month, $%7.0f over term" % (
                res_pricing['name'], res_best, best_pricing[1],
                best_pricing[2], saving_month, res_pricing['term'] * saving_month)

    return prices, res_best, best_pricing


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
    parser.add_option("-m", "--max-reserved", dest="max_reserved", action="store",
                      type="int", default=30,
                      help="Maximum number of instances to consider reserving")
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

    # insert any distribution hacks here

    # our range of interest for reserved slaves
    # must include 0 to correctly calculate savings
    reserved_range = range(0, min(len(counts), options.max_reserved+1))

    price_ondemand = calculate_pricing(counts, ondemand_hourly,
                                      {'name': 'ondemand',
                                       'hourly': ondemand_hourly,
                                        'term': 1,
                                        'upfront': 0},
                                       0)
    print "%15s: $%1.2f/month, considering up to %s reserved instances ..." % \
        ('ondemand', price_ondemand[0], max(reserved_range))

    # calculate the costs
    for p in reserved_pricing:
        r1, r2, r3 = minimize_pricing(counts, ondemand_hourly, p, reserved_range,
                                      textReport=True)
        p['pricing_trend'] = r1
        p['best_count'] = r2
        p['best_pricing'] = r3

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

    plt.bar(np.arange(0,len(counts)), counts, color= 'r', align='center')
    plt.xlabel('Instances used per hour')
    plt.ylabel('Frequency')
    plt.title('Instance usage in the %s\nfrom %s' % (endWindow - startWindow, endWindow))
    plt.grid(True)
    plt.xlim((0,plt.xlim()[1]))

    plt.savefig('usage-reports/instance_histogram.png')

    # create a plot for reserved instance pricing trend
    fig = plt.figure()
    ax = fig.gca()

    for p in reserved_pricing:
      plt.plot(reserved_range, p['pricing_trend'], 'x-', label=p['name'])
    plt.xlabel('Number of reserved instances')
    plt.ylabel('Monthly cost')
    plt.title('Reserved instance cost calculation')
    plt.grid(True)
    plt.legend(ncol=3, prop={'size': 'small'})

    plt.savefig('usage-reports/instance_costing.png')

    # create a bar plot showing total components for each pricing, over the longest term
    fig = plt.figure()
    ax = fig.gca()

    maxterm = max([p['term'] for p in reserved_pricing])
    # to format the data for plotting we make a 2D array
    # each row a set of pricing components, leaving off the total
    p_data = np.zeros(shape=(1+len(reserved_pricing), 4))
    names = ['ondemand']
    p_data[0,:] = price_ondemand[1:] * maxterm
    for i in range(0,len(reserved_pricing)):
        p = reserved_pricing[i]
        names.append('%s x %s' % (p['best_count'], p['name']))
        p_data[i+1,:] = p['best_pricing'][1:] * maxterm
    labels = ['Upfront', 'Fixed', 'Hourly - Reserved', 'Hourly - Ondemand']
    colors = ['r', 'b', 'g' ,'#CCCCCC']
    ind = np.arange(0, 1+len(reserved_pricing))
    width = 0.8
    for i in range(0,4):
        plt.bar(ind+width/2, p_data[:,i], bottom=p_data[:,0:i].sum(axis=1), color=colors[i], label=labels[i])
    plt.xticks(ind+width, names, rotation=25, size='x-small')
    plt.ylabel('Total Cost, USD')
    plt.title('Total costs over %s months' % maxterm)
    plt.legend(ncol=2, prop={'size': 'small'})

    plt.savefig('usage-reports/total_costing.png')
