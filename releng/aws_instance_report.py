import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import datetime
import json

california = pytz.timezone('US/Pacific')
utc = pytz.utc

endWindow = datetime.datetime.now(tz=utc).replace(minute=0, second=0)
startWindow = endWindow - datetime.timedelta(days=14)

##############################################################################################
# read the data from Amazon billing
from aws_retrieve_billing_data import get_report

secrets = json.load(open('portal_secrets'))
username = secrets['portal_username']
password = secrets['portal_password']

if True:
    response = get_report('AmazonEC2', startWindow, endWindow + datetime.timedelta(days=1),
                          username, password, format='csv', period='hours')
    f = open('usage-reports/last-week-EC2-run_c1.xlarge.csv','w')
    for d in response.splitlines(True):
        if 'RunInstances,USW1-BoxUsage:c1.xlarge' in d:
            f.write(d)
    f.close()

times, counts = np.loadtxt("usage-reports/last-week-EC2-run_c1.xlarge.csv",
        unpack=True, delimiter=',', usecols=(4,6),
        converters={ 4: mdates.strpdate2num('%m/%d/%y %H:%M:%S')})

#for i in range(0,len(times)):
#  print mdates.num2date(times[i], tz=california), counts[i]
#   print '%6.6f %f' % (times[i], counts[i])

##############################################################################################
# read data from statusdb to count instances & jobs
import sqlalchemy as sql
import datetime

status_db_meta = sql.MetaData()
engine = sql.create_engine(secrets['status_db'])
status_db_meta.reflect(bind=engine)
status_db_meta.bind = engine

b = status_db_meta.tables['builds']
s = status_db_meta.tables['slaves']
query = sql.select([b.c.id,
                    b.c.starttime,
                    b.c.endtime,
                    s.c.name]).\
            where(sql.and_(b.c.slave_id==s.c.id,
                           s.c.name.like('%-ec2-%'),
                           b.c.endtime >= startWindow,
                           b.c.starttime <= endWindow)).\
            order_by(sql.desc(b.c.starttime))
#query = query.limit(5)
results = query.execute()

oneHour = datetime.timedelta(hours=1)
db_instances = {}
db_builds = {}
offset = datetime.timedelta(hours=7)
for r in results:
#   print r['starttime']-offset, r['endtime']-offset, r['name']
   # keep track of which hours instances were working
   testTime = r['starttime'].replace(minute=0, second=0, tzinfo=utc)
   while testTime < r['endtime'].replace(tzinfo=utc) and testTime < endWindow:
       t = mdates.date2num(testTime)
       db_instances.setdefault(t, set()).update([r['name']])
       db_builds.setdefault(t, 0)
       db_builds[t] += 1
       testTime += oneHour

# squash the set of instances to a count, sort for easy inspection
times_db = []
inst_counts_db = []
for k in sorted(db_instances.keys()):
    times_db.append(k)
    inst_counts_db.append(len(db_instances[k]))
times_db = np.array(times_db)
inst_counts_db = np.array(inst_counts_db)

times2_db = np.array(db_builds.keys())
build_counts_db = np.array(db_builds.values())

#for i in range(0,len(times_db)):
#  print mdates.num2date(times_db[i], tz=california), inst_counts_db[i]


##############################################################################################
# create a plot for last 48 hours
fig = plt.figure()
ax = fig.gca()
ax.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%H%M', tz=california))

width = 0.85 / 2 / 24
rect1 = plt.bar(times-width/2, counts, width=width, color='c', align='center', label='Amazon Billing', linewidth=0)
rect2 = plt.bar(times_db+width/2, inst_counts_db, width=width, color='m', align='center', label='StatusDB', linewidth=0)
plt.xlabel('Pacific time')
plt.ylabel('Instances Used')
plt.grid(True)

xpadding = datetime.timedelta(minutes=30)
ypadding = 5
maxInstance = 80
ax.set_ylim((0, maxInstance+ypadding))
ax.set_xlim((endWindow-datetime.timedelta(days=2)-xpadding, endWindow+xpadding))

# throw on a max instance line
rect3 = plt.plot(ax.get_xlim(), (maxInstance, maxInstance), 'ro-', label='Instance Limit')

# throw on a dodgy data box for amazon lag
xdodgy = datetime.timedelta(hours=3)
if (datetime.datetime.now(tz=utc) - endWindow) < xdodgy:
   plt.fill_between((endWindow-xdodgy, endWindow+xpadding), 0, 85, alpha=0.5, color='grey')

plt.legend(bbox_to_anchor=(0., 1.01, 1., .085), loc=3,
       ncol=3,  mode="expand", borderaxespad=0.)
plt.text(1.09, 0.5, 'Generated at %s' % datetime.datetime.now().replace(microsecond=0),
         rotation='vertical', transform = ax.transAxes, verticalalignment='center', size='x-small')

plt.savefig('usage-reports/instance_2day.png')

##############################################################################################
# create a plot for last month
fig = plt.figure()
ax = fig.gca()
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%H%M', tz=california))

width=1.0/24
plt.bar(times, counts, width=width, color='c', align='center', label='Amazon Billing', linewidth=0)
plt.xlabel('Pacific time')
plt.ylabel('Instances Used')
plt.grid(True)

ax.set_ylim((0, maxInstance+ypadding))
ax.set_xlim((startWindow-xpadding, endWindow+xpadding))

# throw on a max instance line
rect3 = plt.plot(ax.get_xlim(), (maxInstance, maxInstance), 'ro-', label='Instance Limit')

# throw on a dodgy data box for amazon lag
xdodgy = datetime.timedelta(hours=3)
if (datetime.datetime.now(tz=utc) - endWindow) < xdodgy:
   plt.fill_between((endWindow-xdodgy, endWindow+xpadding), 0, 85, alpha=0.5, color='grey')

plt.legend(bbox_to_anchor=(0., 1.01, 1., .085), loc=3,
       ncol=3,  mode="expand", borderaxespad=0.)
plt.text(1.09, 0.5, 'Generated at %s' % datetime.datetime.now().replace(microsecond=0),
         rotation='vertical', transform = ax.transAxes, verticalalignment='center', size='x-small')

plt.savefig('usage-reports/instance_14day.png')

