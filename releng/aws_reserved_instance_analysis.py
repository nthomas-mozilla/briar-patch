import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import datetime
import json

california = pytz.timezone('US/Pacific')
utc = pytz.utc

endWindow = datetime.datetime.now(tz=utc).replace(minute=0, second=0, microsecond=0)
startWindow = endWindow - datetime.timedelta(days=31)

##############################################################################################
# read the data from Amazon billing
from aws_retrieve_billing_data import get_report

secrets = json.load(open('portal_secrets'))
username = secrets['portal_username']
password = secrets['portal_password']

counts = {}
if False:
    response = get_report('AmazonEC2', startWindow, endWindow + datetime.timedelta(days=1),
                          username, password, format='csv', period='hours')
    f = open('usage-reports/instance-run_c1.xlarge.csv','w')
    for d in response.splitlines(True):
        if 'RunInstances,USW1-BoxUsage:c1.xlarge' in d:
            f.write(d)
    f.close()

times, raw_counts = np.loadtxt("usage-reports/instance-run_c1.xlarge.csv",
        unpack=True, delimiter=',', usecols=(4,6),
        converters={ 4: mdates.strpdate2num('%m/%d/%y %H:%M:%S')})

##############################################################################################
# convert to a list where the index is the instance usage, value is frequency
# diy histogram
counts = np.zeros(max(raw_counts)+1)
for r in raw_counts:
   counts[r] += 1

#print "raw_counts: %s" % raw_counts
#print "counts:"
#for i in range(0,len(counts)):
#  print "%3.0f  %3.0f" % (i, counts[i])

##############################################################################################
# do billing calculation

# pricing for Linux 'Heavy Utilization Reserved Instances' of type
#                   'High-CPU On-Demand Instances' (aka c1.xlarge) in 
#                   'US West (Northen California)' (aka USW1)
# NB, Heavy Utilisation Reserved Instances are always charged the hourly fee
#   see http://aws.amazon.com/ec2/reserved-instances/#5
# we get charged 0.72 for on demand now but pricing page says 0.744
# we neglect other components like IOps and transfer

ondemand_instance = 0.72    # $/hour
reserved_instance = 0.22    # $/hour
reserved_fee      = 3100    # $ 
reserved_term     = 36      # months
# see also $2000 for 1yr + $0.25/hour
# see also $3100 for 3yr + $0.22/hour

one_month         = 365.25/12 * 24 # hours / month

# list of results, index is # of reserved instances
prices = []

reserved_range = range(0,31)

for r_count in reserved_range:
    r_price = (reserved_fee/reserved_term + \
               reserved_instance * one_month) * r_count
    for i in range(r_count+1, len(counts)):
        r_price += ondemand_instance * (i - r_count) * counts[i]
    prices.append(r_price)

print "prices:"
for i in reserved_range:
  print "%3.0f  %10.2f" % (i, prices[i])

reserved_best = prices.index(min(prices))
saving_month = prices[0] - prices[reserved_best]
print "\nCheapest cost / month - %1.0f instances" % reserved_best
print " - upfront cost (%s month term): $%1.2f" % (reserved_term, reserved_best * reserved_fee) 
print " - fixed monthly cost: $%1.2f" % (reserved_instance * one_month * reserved_best)
print " - estimated savings per month: $%1.2f" % (saving_month)
print " - estimated savings over %s month term: $%1.2f" % (reserved_term, reserved_term * saving_month)

##############################################################################################
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

##############################################################################################
# create a histogram plot for instance usage
fig = plt.figure()
ax = fig.gca()

plt.hist(raw_counts, range(0,81), color= 'r', align='left')
plt.xlabel('Instances used per hour')
plt.ylabel('Frequency')
plt.title('Instance Usage between %s and %s' % (startWindow, endWindow))
plt.grid(True)

plt.savefig('usage-reports/instance_histogram.png')

##############################################################################################
# create a plot for reserved instance_pricing

fig = plt.figure()
ax = fig.gca()

plt.plot(reserved_range, prices, 'r.-')
plt.xlabel('Number of reserved instances')
plt.ylabel('Monthly cost')
plt.grid(True)

plt.savefig('usage-reports/instance_costing.png')

