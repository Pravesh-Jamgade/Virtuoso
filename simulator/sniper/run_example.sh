#!/bin/bash


# This script runs the Sniper simulator with a specified configuration file and workload.
# Usage: ./run_example.sh 

helpFunction()
{
   echo ""
   echo "Usage: $0 -a parameterA -b parameterB -c parameterC"
   echo -e "\t-a Application"
   echo -e "\t-b Input"
   echo -e "\t-c Description of what is parameterC"
   exit 1 # Exit script after printing help
}

while getopts "a:b:c:" opt
do
   case "$opt" in
      a ) parameterA="$OPTARG" ;;
      b ) parameterB="$OPTARG" ;;
      c ) parameterC="$OPTARG" ;;
      ? ) helpFunction ;; # Print helpFunction in case parameter is non-existent
   esac
done


CONFIG_FILE=./config/virtuoso_configs/virtuoso_baseline.cfg

WORKLOAD=ls

./run-sniper -c $CONFIG_FILE -d ./example_output --genstats -- $parameterA $parameterB


#Check if the command was successful by looking for sim.stats in the output directory

if [ -f ./example_output/sim.stats ]; then
    echo "Simulation completed successfully. Output is in ./example_output."
else
    echo "Simulation failed. Check the configuration and workload."
fi

rm -rf ./example_output
