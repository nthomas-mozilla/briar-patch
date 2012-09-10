set term png size 800, 350 enhanced font "ttf-bitstream-vera-1.10/Vera.ttf" 10

# set datafile missing "?"
set datafile separator ","

set timefmt "%m/%d/%y %H:%M:%S"
set xdata time

set style data points
set pointsize 0.5

set key off
set grid ytics xtics
set ylabel "# of instances"

#set autoscale xfixmin
#set autoscale xfixmax
#set autoscale yfixmax

# all data
set format x "%d %b\n%H:%M"
set xlabel "Time (Day HH:MM GMT)"
set output "running_c1.xlarge_instances_week.png"
set title "Instances report (c1.xlarge)"
set yrange [0:85]
plot "usage-reports/last-week-EC2-run_c1.xlarge.csv" using 5:7 with impulses, \
     80

# last day
set format x "%a \n%H:%M"
set xlabel "Time (Day HH:MM GMT)"
set output "running_c1.xlarge_instances_day.png"
set title "Instances report (c1.xlarge)"
set yrange [0:85]
plot "< tail -24 usage-reports/last-week-EC2-run_c1.xlarge.csv" using 5:7, \
     80

# TO DO
## get total number of slaves programatically
## convert from GMT to Pacific
