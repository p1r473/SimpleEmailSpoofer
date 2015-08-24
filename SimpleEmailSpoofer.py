#! /usr/bin/env python


import re
import smtplib
import argparse
import logging

import emailprotectionslib.dmarc as dmarclib
import emailprotectionslib.spf as spflib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from libs.PrettyOutput import *


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--to", dest="to_address", help="Email address to send to")
    parser.add_argument("-f", "--from", dest="from_address", help="Email address to send from")
    parser.add_argument("-n", "--from_name", dest="from_name", help="From name")

    parser.add_argument("-j", "--subject", dest="subject", nargs="?", help="Subject for the email")
    parser.add_argument("-e", "--email_filename", dest="email_filename", nargs="?",
                        help="Filename containing an HTML email")

    parser.add_argument("-a", "--to_address_filename", dest="to_address_filename", nargs="?",
                        help="Filename containing a list of TO addresses")

    parser.add_argument("-c", "--check", dest="spoof_check", action="store_true",
        help="Check to ensure FROM domain can be spoofed from (default)", default=True)
    parser.add_argument("-x", "--nocheck", dest="spoof_check", action="store_false",
        help="Do not check that FROM domain can be spoofed from")
    parser.add_argument("--force", dest="force", action="store_true", default=False,
        help="Force the email to send despite protections")


    email_options = parser.add_argument_group("Email Options")
    email_options.add_argument("-i", "--interactive", action="store_true", dest="interactive_email",
        help="Input email in interactive mode")

    smtp_options = parser.add_argument_group("SMTP options")
    smtp_options.add_argument("-s", "--server", dest="smtp_server",
        help="SMTP server IP or DNS name (default localhost)", default="localhost")
    smtp_options.add_argument("-p", "--port", dest="smtp_port", type=int, help="SMTP server port (default 25)",
        default=25)

    return parser.parse_args()


def get_ack(force):
    output_info("To continue: [yes/no]")
    if force is False:
        yn = raw_input()
        if yn != "yes":
            return False
        else:
            return True
    elif force is True:
        output_indifferent("Forced yes")
        return True
    else:
        raise TypeError("Passed in non-boolean")


def get_interactive_email():
    email_text = ""

    # Read email text into email_text
    output_info("Enter HTML email line by line")
    output_info("Press CTRL+D to finish")
    while True:
        try:
            line = raw_input("| ")
            email_text += line + "\n"
        except EOFError:
            output_info("Email captured.")
            break

    return email_text


def get_file_email():
    email_text = ""
    try:
        with open(args.email_filename, "r") as infile:
            output_info("Reading " + args.email_filename + " as email file")
            email_text = infile.read()
    except IOError:
        output_error("Could not open file " + args.email_filename)
        exit(-1)

    return email_text


def is_domain_spoofable(from_address, to_address):

    email_re = re.compile(".*@(.*\...*)")

    from_domain = email_re.match(from_address).group(1)
    to_domain = email_re.match(to_address).group(1)
    output_info("Checking if from domain " + Style.BRIGHT + from_domain + Style.NORMAL + " is spoofable")

    if from_domain == "gmail.com":
        if to_domain == "gmail.com":
            output_bad("You are trying to spoof from a gmail address to a gmail address.")
            output_bad("The Gmail web application will display a warning message on your email.")
            if not get_ack(args.force):
                output_bad("Exiting")
                exit(1)
        else:
            output_indifferent("You are trying to spoof from a gmail address.")
            output_indifferent("If the domain you are sending to is controlled by Google Apps the web application will display a warning message on your email.")
            if not get_ack(args.force):
                output_bad("Exiting")
                exit(1)

    if args.spoof_check:
        spoofable = False
        spf = spflib.SpfRecord.from_domain(from_domain)
        if spf is not None:

            if spf.all_string is not None and not (spf.all_string == "~all" or spf.all_string == "-all"):
                spoofable = True

        else:
            spoofable = True

        dmarc = dmarclib.DmarcRecord.from_domain(from_domain)
        if dmarc is not None:
            output_info(str(dmarc))

            if dmarc.policy is None or not (dmarc.policy == "reject" or dmarc.policy == "quarantine"):
                spoofable = True

            if dmarc.pct is not None and dmarc.pct != str(100):
                output_indifferent("DMARC pct is set to " + dmarc.pct + "% - Spoofing might be possible")

            if dmarc.rua is not None:
                output_indifferent("Aggregate reports will be sent: " + dmarc.rua)
                if not get_ack(args.force):
                    output_bad("Exiting")
                    exit(1)

            if dmarc.ruf is not None:
                output_indifferent("Forensics reports will be sent: " + dmarc.ruf)
                if not get_ack(args.force):
                    output_bad("Exiting")
                    exit(1)
        else:
            spoofable = True

        if not spoofable:
            output_bad("From domain " + Style.BRIGHT + from_domain + Style.NORMAL + " is not spoofable.")

            if not args.force:
                output_bad("Exiting. (-f to override)")
                exit(2)
            else:
                output_indifferent("Overriding...")
        else:
            output_good("From domain " + Style.BRIGHT + from_domain + Style.NORMAL + " is spoofable!")

    output_info("Sending to " + args.to_address)


if __name__ == "__main__":
    args = get_args()

    print args

    email_text = ""
    if args.interactive_email:
        email_text = get_interactive_email()
    else:
        email_text = get_file_email()

    to_addresses = []
    if args.to_address is not None:
        to_addresses.append(args.to_address)
    elif args.to_address_filename is not None:
        try:
            with open(args.to_address_filename, "r") as to_address_file:
                to_addresses = to_address_file.readlines()
                print to_addresses
        except IOError as e:
            logging.error("Could not locate file %s", args.to_address_filename)
            raise e
    else:
        logging.error("Could not load input file names")
        exit(1)

    try:
        output_info("Connecting to SMTP server at " + args.smtp_server + ":" + str(args.smtp_port))
        server = smtplib.SMTP(args.smtp_server, args.smtp_port)
        msg = MIMEMultipart("alternative")
        msg.set_charset("utf-8")

        if args.from_name is not None:
            output_info("Setting From header to: " + args.from_name + "<" + args.from_address + ">")
            msg["From"] = args.from_name + "<" + args.from_address + ">"
        else:
            output_info("Setting From header to: " + args.from_address)
            msg["From"] = args.from_address

        if args.subject is not None:
            output_info("Setting Subject header to: " + args.subject)
            msg["Subject"] = args.subject

        for to_address in to_addresses:
            msg["To"] = to_address
            msg.attach(MIMEText(email_text, 'html', 'utf-8'))
            print msg["To"] + ", " + msg["Subject"]
            server.sendmail(args.from_address, to_address, msg.as_string())
            output_good("Email Sent to " + to_address)

    except smtplib.SMTPException as e:
        output_error("Error: Could not send email")
        raise e
