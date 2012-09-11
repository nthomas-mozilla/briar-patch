#cd ~/briar-patch/releng/

PYTHON=~/virtualenvs/aws/bin/python

# get 2 last week's data
$PYTHON aws_retrieve_billing_data.py -k portal_secrets \
  -s AmazonEC2 -p hours \
  `date +'%Y-%m-%d' -d '14 days ago'` \
  `date +'%Y-%m-%d' -d 'tomorrow'`  > usage-reports/last-week-EC2.csv
grep 'RunInstances,USW1-BoxUsage:c1.xlarge' usage-reports/last-week-EC2.csv > usage-reports/last-week-EC2-run_c1.xlarge.csv

# get total number of compute instances

gnuplot instances.gnuplot
chmod a+r *.png
cp -p *.png ~/public_html/aws_test/
