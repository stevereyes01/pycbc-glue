#!/usr/bin/env python
#
# Copyright (C) 2009  Larne Pekowsky, based on glitch-page.sh by Duncan
# Brown
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#


from optparse import OptionParser

try:
    import sqlite3
except ImportError:
    # pre 2.5.x
    from pysqlite2 import dbapi2 as sqlite3

import sys
import os
import glob

import glue.segments

from glue.ligolw import ligolw
from glue.ligolw import lsctables
from glue.ligolw import utils
from glue.ligolw.utils import ligolw_sqlite
from glue.ligolw import dbtables

from glue.segmentdb import query_engine

from glue import gpstime

import glob
import time
import datetime
import StringIO

#
# =============================================================================
#
#                                 Command Line
#
# =============================================================================
#

def parse_command_line():
    """
    Parse the command line, return an options object
    """

    parser = OptionParser(
        version     = "%prog CVS $Header$",
        usage       = "%prog --trigger-dir dir --segments url --html-file file --ifo ifo --timestamp-file [other options]",
        description = "Updates or creates the html with recnet glitch summary information"
	)

    parser.add_option("-t", "--trigger-dir",   metavar="dir",  help = "Location of XML files containing sngl_inspiral tables")
    parser.add_option("-s", "--segments",      metavar="url",  help = "URL to contact for DQ flags (ldbd: or file:)")
    parser.add_option("-f", "--html-file",     metavar="file", help = "Location of html file to write")
    parser.add_option("-i", "--ifo",           metavar="ifo",  help = "IFO")
    parser.add_option("-g", "--timestamp-file", metavar="file", help = "Location of file storing last run time")
    parser.add_option("-m", "--min-glitch-snr", metavar="snr",  help = "Minimum SNR to be considered a glitch (default=15.0)",  default="15.0")
    parser.add_option("-k", "--known-count",    metavar="known_count", help = "Max. number of triggers with DQ flags to print (default=10)", default="10")
    parser.add_option("-u", "--unknown-count",  metavar="unknown_count", help = "Max. number of triggers without DQ flags to print (default=10)", default="10")

    options, others = parser.parse_args()

    # Make sure we have all required parameters
    if not (options.trigger_dir and options.segments and options.ifo and options.timestamp_file and options.html_file):
        print "Usgae: %prog --trigger-dir dir --segments url --html-file file --ifo ifo --timestamp-file [other options]"
        sys.exit(-1)

    return options



def generate_html(outf, triggers, colors):
    # echo "<p><tt><a href=\"${xmlfile}\">${xmlfile}</a></tt>" >> ${htmlfile}
    print >>outf, '<p>'
    print >>outf, '<table border=1>'
    print >>outf, '  <tr bgcolor="#9999ff"><th>ifo</th><th>end_time</th><th>end_time_ns</th><th>snr</th><th>eff_distance</th><th>f_final</th><th>ttotal</th><th>Q scan</th><th>DQ flags</th></tr>'

    for count, trig in enumerate(triggers):
        print >>outf, '  <tr valign="top" bgcolor="%s">' % colors[count % 2]
        for res in trig[:-1]:
            print >>outf, '    <td>%s</td>' % res
        print >>outf, '    <td><a href="http://ldas-jobs.ligo-wa.caltech.edu/~inspiralbns/qscans/%d.%d">Q Scan</a></td>' % (trig[1], trig[2])

        print >>outf, '    <td>'

        for name, value in trig[-1].items():
            if name == 'DMT-SCIENCE':
                print >>outf, '      <b>Science</b><br>'
            elif name == 'DMT-INJECTION':
                print >>outf, '      <b>Injection</b><br>'
            else:
                print >>outf, '      %s %s %s<br>' % (name, value[0], value[2])
        print >>outf, '    </td>'

        print >>outf, '  </tr>'
    print >>outf, '</table>'

    print >>outf
    print >>outf




def file_filter(file_name, start_time, end_time):
    """Given a filename of the form /root_path/H-DQ_Segments-time-16.xml and start and end
    times returns true if the file falls into the time interval."""
    pieces    = file_name.split('-')

    file_time = int(pieces[-2])

    return file_time >= (start_time-16) and file_time <= (end_time+16) 

def setup_files(dir_name, gps_start_time, gps_end_time):
    # extract directory from URL
    glob_pattern = dir_name + '/*.xml'

    # Filter out the ones that are outside our time range
    xml_files = filter(lambda x: file_filter(x, gps_start_time, gps_end_time), glob.glob(glob_pattern))

    # TODO: This should have a better name that includes the
    # start and end times
    temp_db      = 'glitch-temp.db'

    target     = dbtables.get_connection_filename(temp_db, None, True, False)
    connection = ligolw_sqlite.setup(target)

    ligolw_sqlite.insert(connection, xml_files) # [temp_xml])

    return connection
    


#
# =============================================================================
#
#                                     Main
#
# =============================================================================
#

if __name__ == '__main__':
    options = parse_command_line()    

    # Run up to now
    gps_end_time = gpstime.GpsSecondsFromPyUTC(time.time())

    # Find the last time we ran (in principle we could get this from the time
    # stamp on the HTML file, but we should allow for the possibility that 
    # someone might hand-edit that file)
    if os.path.exists(options.timestamp_file):
        f = open(options.timestamp_file)
        gps_start_time = int(f.next())
        f.close()
    else:
        # Looks like we've never run before, start a day ago
        gps_start_time = gps_end_time - (60 * 60 * 24)


    # Load the relevant trigger XML files into a sqlite DB and
    # get a connection
    connection = setup_files(options.trigger_dir, gps_start_time, gps_end_time)

    # Get the triggers
    # Note, the S5 version of this script had the condition
    #    search = 'FindChirpSPtwoPN' 
    # The triggers from MBTA don't set this, alough it could if desirable.
    # 
    # When hitting DB2 we could use the following query:
    #
    #  SELECT sngl_inspiral.ifo, 
    #         sngl_inspiral.end_time,
    #         sngl_inspiral.end_time_ns,
    #         sngl_inspiral.snr, 
    #         sngl_inspiral.eff_distance,
    #         sngl_inspiral.f_final, 
    #         sngl_inspiral.ttotal
    #  FROM sngl_inspiral 
    #  WHERE (sngl_inspiral.end_time, sngl_inspiral.snr) IN 
    #         (select end_time, MAX(snr) AS snr 
    #          FROM sngl_inspiral
    #          WHERE end_time >= ? AND
    #                end_time <  ? AND
    #                ifo = ? AND
    #                snr >= 15.0 
    #          GROUP BY end_time
    #          ORDER BY snr desc)
    #  AND sngl_inspiral.ifo = ? 
    #  ORDER BY snr DESC""",  (start_time, end_time, ifo, ifo) )
    #
    # But sqlite doesn't allow this, since:
    #   SQL error: only a single result allowed for a SELECT that is part of an expression
    #
    # So we have to be a little trickier...
    #

    rows = connection.cursor().execute("""SELECT sngl_inspiral.ifo, 
             sngl_inspiral.end_time,
             sngl_inspiral.end_time_ns,
             sngl_inspiral.snr, 
             sngl_inspiral.eff_distance,
             sngl_inspiral.f_final, 
             sngl_inspiral.ttotal
      FROM sngl_inspiral 
      WHERE (cast(sngl_inspiral.end_time as char) || " -- " || cast(sngl_inspiral.snr as char)) IN
             (SELECT cast(end_time as char) || " -- " || cast(MAX(snr) as char)
              FROM sngl_inspiral
              WHERE end_time >= ? AND
                    end_time <  ? AND
                    ifo = ? AND
                    snr >= ?
              GROUP BY end_time
              ORDER BY snr desc)
      AND sngl_inspiral.ifo = ? 
      ORDER BY snr DESC""",  (gps_start_time, gps_end_time, options.ifo, options.min_glitch_snr, options.ifo) )


    # ligolw_sicluster --cluster-window ${clusterwindow} --sort-descending-snr ${xmlfile}

    known_trigs   = []
    unknown_trigs = []
    
    for ifo, end_time, end_time_ns, snr, e_dist, f_final, t_tot in rows:
        trig_time = end_time
        if end_time_ns >= 500000000:
            trig_time += 1
    
        # Find the flags on at this time
        flags = {}

        pipe  = os.popen('ligolw_dq_query --segment=%s --report %d --include-segments %s' % (options.segments, end_time, ifo))
        for line in pipe:
            flag, beforet, timet, aftert = filter(lambda x: x != '', line.split())
    
            # We're not interested in the ones that aren't active at this time
            # (this could be an option to dg_query)
            if not beforet.endswith(')'):
                ifo, name, version = flag.split(':')
                flags[name] = (beforet, timet, aftert)
    
    
        if 'DMT-INJECTION' in flags:
            if len(known_trigs) < options.known_count:
                known_trigs.append((ifo, end_time, end_time_ns, snr, e_dist, f_final, t_tot, flags))
        elif len(unknown_trigs) < options.unknown_count:
            unknown_trigs.append((ifo, end_time, end_time_ns, snr, e_dist, f_final, t_tot, flags))
    
        os.system('nohup condor_run "~qonline/qscan/bin/qscan.sh %d.%d" < /dev/null &>/dev/null &' % (end_time, end_time_ns))

        # Print no more than the top ten known and unknown triggers
        # (the ranking is done by the 'ODRER BY snr DESC' in the query above)
    
        if len(known_trigs) == options.known_count and len(unknown_trigs) == options.unknown_count:
            break
    
    
    # Convert to html, prepend to the file.
    out_tmp = StringIO.StringIO()
   
    # Could these be done in Python?
    start_time_str = os.popen('tconvert %d' % gps_start_time).next().strip()
    end_time_str   = os.popen('tconvert %d' % gps_end_time).next().strip()

    print >>out_tmp, "<h3>%s through %s</h3>" % (start_time_str, end_time_str)

    print >>out_tmp, '<h3>Glitches without associated DQ flag</h3>'
    generate_html(out_tmp, unknown_trigs, ['#ffdddd', '#ffcccc'])
    

    print >>out_tmp, '<h3>Glitches with associated DQ flag</h3>'
    generate_html(out_tmp, known_trigs, ['#ddffdd', '#ccffcc'])

    print >>out_tmp, "<hr>"

    if os.path.exists(options.html_file):
        in_tmp = open(options.html_file)
        for l in in_tmp:
            print >>out_tmp, l
        in_tmp.close()

    out_html = open(options.html_file,'w')
    print >>out_html, out_tmp.getvalue()
    out_html.close()

    # All done, update the timestamp
    f = open(options.timestamp_file, 'w')
    print >>f,  gps_end_time
    f.close()

    # Clean up after ourselves.
    os.remove('glitch-temp.db')
