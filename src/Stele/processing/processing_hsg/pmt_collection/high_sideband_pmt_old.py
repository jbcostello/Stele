import os
import errno
import json
import numpy as np
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
from .processing.processing_HSG import helperFunctions as procHSGHelp
from .PMT_collection.pmt import PMT
from .PMT_collection.HighSidebandPMT import HighSidebandPMT

np.set_printoptions(linewidth=500)


class HighSidebandPMTOld(PMT):
    """
    Old version: Replaced March 01, 2017

    Class initialized by loading in data set.

    Multiple copies of the same sideband were stacked as raw data and combined,
    effectively causing (2) 10-pt scans to be treated the same as (1) 20pt
    scan.  This works well until you have photon counted pulses.
    """
    def __init__(self, file_path, verbose=False):
        """
        Initializes a SPEX spectrum.  It'll open a single file, then read
        the data from that file using .add_sideband().  The super's init will
        handle the parameters and the description.

        attributes:
            self.parameters - dictionary of important experimental parameters,
                              created in PMT
            self.sb_dict - keys are sideband order, values are PMT data arrays
            self.sb_list - sorted list of included sidebands

        :param file_path: path to the current file
        :type file_path: str
        :param verbose: Flag to see the nitty gritty details
        :type verbose: bool
        :return:
        """
        # Creates the json parameters dictionary
        super(HighSidebandPMT, self).__init__(file_path)
        self.fname = file_path
        self.parameters["files included"] = [file_path]
        with open(file_path, 'r') as f:
            sb_num = int(f.readline()[1:])
        raw_temp = np.genfromtxt(file_path, comments='#', delimiter=',')[3:, :]
        self.initial_sb = sb_num
        self.initial_data = np.array(raw_temp)
        self.sb_dict = {sb_num: np.array(raw_temp)}
        self.sb_list = [sb_num]

    def add_sideband(self, other):
        """
        This bad boy will add another PMT sideband object to the sideband
        spectrum of this object.  It handles when you measure the same sideband
        twice.  It assumes both are equally "good"

        It currently doesn't do any sort of job combining dictionaries or
        anything, but it definitely could, if you have two incomplete
        dictionaries

        :param other: the new sideband data to add to the larger spectrum.
                      Add means append, no additino is performed
        :type other: HighSidebandPMT
        :return:
        """
        """
        This bad boy will add another PMT sideband object to the sideband
        spectrum of this object

        It currently doesn't do any sort of job combining dictionaries or
        anything, but it definitely could
        """
        self.parameters["files included"].append(other.fname)

        if other.initial_sb in self.sb_list:
            self.sb_list.append(other.initial_sb)

        # Make things comma delimited?
        try:
            self.sb_dict[other.initial_sb].vstack((other.initial_data))
        except Exception:
            self.sb_dict[other.initial_sb] = np.array(other.initial_data)

    def process_sidebands(self, verbose=False):
        """
        This bad boy will clean up the garbled mess that is the object before
        hand, including clearing out misfired shots and doing the averaging.

        Affects:
            self.sb_dict = Averages over sidebands

        Creates:
            self.sb_list = The sideband orders included in this object.

        :param verbose: Flag to see the nitty gritty details.
        :type verbose: bool
        :return: None
        """

        for sb_num, sb in list(self.sb_dict.items()):
            if sb_num == 0:
                # This way the FEL doesn't need to be on during laser
                # line measurement
                fire_condition = -np.inf
            else:
                # Say FEL fired if the cavity dump signal is
                # more than half the mean of the cavity dump signal
                fire_condition = np.mean(sb[:, 2]) / 2
            frequencies = sorted(list(set(sb[:, 0])))

            temp = None
            for freq in frequencies:
                data_temp = np.array([])
                for point in sb:
                    if point[0] == freq and point[2] > fire_condition:
                        data_temp = np.hstack((data_temp, point[3]))
                try:
                    temp = np.vstack((temp, np.array([
                        freq, np.mean(data_temp),
                        np.std(data_temp) / np.sqrt(len(data_temp))
                        ])))
                except Exception:
                    temp = np.array([
                        freq, np.mean(data_temp),
                        np.std(data_temp) / np.sqrt(len(data_temp))
                        ])
            # turn NIR freq into eV
            temp[:, 0] = temp[:, 0] / 8065.6
            temp = temp[temp[:, 0].argsort()]
            self.sb_dict[sb_num] = np.array(temp)
        self.sb_list = sorted(self.sb_dict.keys())
        if verbose:
            print("Sidebands included", self.sb_list)

    def integrate_sidebands(self, verbose=False):
        """
        This method will integrate the sidebands to find their strengths, and
        then use a magic number to define the width, since they are currently
        so utterly undersampled for fitting.

        It is currently the preferred method for calculating sideband
        strengths.  self.fit_sidebands is probably better with better-sampled
        lines.

        Creates:
        self.sb_results = full list of integrated data. Column order is:
                          [sb order, Freq (eV), "error" (eV), Integrate area
                          (arb.), area error, "Linewidth" (eV),
                          "Linewidth error" (eV)
        self.full_dict = Dictionary where the SB order column is removed and
                         turned into the keys.  The values are the rest of that
                         sideband's results.

        :param verbose: Flag to see the nitty gritty details
        :type verbose: bool
        :return: None
        """
        self.full_dict = {}
        for sideband in list(self.sb_dict.items()):
            index = np.argmax(sideband[1][:, 1])
            nir_frequency = sideband[1][index, 0]
            area = np.trapz(np.nan_to_num(
                sideband[1][:, 1]), sideband[1][:, 0]
                )
            # Divide by the step size?
            error = np.sqrt(np.sum(np.nan_to_num(
                sideband[1][:, 2]) ** 2)) / 8065.6
            if verbose:
                print("order", sideband[0])
                print("area", area)
                print("error", error)
                print("ratio", area / error)
            details = np.array([
                sideband[0], nir_frequency, 1 / 8065.6, area, error,
                2 / 8065.6, 1 / 8065.6
                ])
            if area < 0:
                if verbose:
                    print("area less than 0", sideband[0])
                continue
            # Two seems like a good cutoff?
            elif area < 1.5 * error:
                if verbose:
                    print("I did not keep sideband ", sideband[0])
                continue
            try:
                self.sb_results = np.vstack((self.sb_results, details))
            except Exception:
                self.sb_results = np.array(details)
            self.full_dict[sideband[0]] = details[1:]
        try:
            self.sb_results = self.sb_results[self.sb_results[:, 0].argsort()]

        except (IndexError, AttributeError):
            # IndexError where there's only one sideband
            # AttributeError when there aren't any (one sb which wasn't fit)
            pass

    def fit_sidebands(self, plot=False, verbose=False):
        """
        This method will fit a gaussian to each of the sidebands provided in
        the self.sb_dict and make a list just like in the EMCCD version.  It
        will also use the standard error of the integral of the PMT peak as the
        error of the gaussian area instead of that element from the covariance
        matrix.  Seems more legit.

        attributes:
        self.sb_results: the numpy array that contains all of the fit info just
                         like it does in the CCD class.
        self.full_dict = A dictionary version of self.sb_results

        :param plot: Flag to see the results plotted
        :type plot: bool
        :param verbose: Flag to see the nitty gritty details
        :type verbose: bool
        :return: None
        """
        sb_fits = {}
        for sideband in list(self.sb_dict.items()):
            if verbose:
                print("Sideband number", sideband[0])
                print("Sideband data:\n", sideband[1])
            index = np.argmax(sideband[1][:, 1])
            nir_frequency = sideband[1][index, 0]
            peak = sideband[1][index, 1]
            width_guess = 0.0001  # Yep, another magic number
            p0 = [nir_frequency, peak * width_guess, width_guess, 0.00001]

            if verbose:
                x_vals = np.linspace(np.amin(sideband[1][:, 0]),
                                     np.amax(sideband[1][:, 0]), num=50)
                plt.plot(x_vals, procHSGHelp.gauss(x_vals, *p0),
                         label="fit :{}".format(sideband[1]))
                print("p0:", p0)
            try:
                coeff, var_list = curve_fit(
                    gauss, sideband[1][:, 0], sideband[1][:, 1],
                    sigma=sideband[1][:, 2], p0=p0
                    )
                coeff[1] = abs(coeff[1])
                coeff[2] = abs(coeff[2])
                if verbose:
                    print("coeffs:", coeff)
                    print("stdevs:", np.sqrt(np.diag(var_list)))
                    print("integral", np.trapz(
                        sideband[1][:, 1], sideband[1][:, 0]
                        ))
                # The error on where the sideband is should be small
                if np.sqrt(np.diag(var_list))[0] / coeff[0] < 0.5:
                    sb_fits[sideband[0]] = np.concatenate((
                        np.array([sideband[0]]), coeff,
                        np.sqrt(np.diag(var_list))
                        ))
                    # print "error then:", sb_fits[sideband[0]][6]
                    relative_error = (
                        np.sqrt(sum([
                            x ** 2 for x in sideband[1][index - 1:index + 2, 2]
                            ]))
                        / np.sum(sideband[1][index - 1:index + 2, 1]))
                    if verbose:
                        print("relative error:", relative_error)
                    sb_fits[sideband[0]][6] = coeff[1] * relative_error
                    # print "error now:", sb_fits[sideband[0]][6]
                    if plot:
                        x_vals = np.linspace(np.amin(sideband[1][:, 0]),
                                             np.amax(sideband[1][:, 0]), num=50
                                             )
                        plt.plot(x_vals, procHSGHelp.gauss(x_vals, *coeff))
                        # plt.plot(x_vals, gauss(x_vals, *p0))
                else:
                    print("what happened?")
            except Exception:
                print("God damn it, Leroy.\nYou couldn't fit this.")
                sb_fits[sideband[0]] = None

        for result in sorted(sb_fits.keys()):
            try:
                self.sb_results = np.vstack((self.sb_results, sb_fits[result]))
            except Exception:
                self.sb_results = np.array(sb_fits[result])

        self.sb_results = self.sb_results[:, [0, 1, 5, 2, 6, 3, 7, 4, 8]]
        self.sb_results = self.sb_results[:, :7]
        if verbose:
            print("And the results, please:\n", self.sb_results)

        self.full_dict = {}
        for sb in self.sb_results:
            self.full_dict[sb[0]] = np.asarray(sb[1:])

    def laser_line(self, verbose=False):
        """
        This method is designed to scale everything in the PMT to the
        conversion efficiency based on our measurement of the laser line with a
        fixed attenuation.

        Creates:
            self.parameters['normalized?'] = Flag to specify if the laser has
            been accounted for.

        :return: None
        """

        if 0 not in self.sb_list:
            self.parameters['normalized?'] = False
            return
        else:
            laser_index = np.where(self.sb_results[:, 0] == 0)[0][0]
            if verbose:
                print("sb_results", self.sb_results[laser_index, :])
                print("laser_index", laser_index)

            laser_strength = np.array(self.sb_results[laser_index, 3:5])

            if verbose:
                print("Laser_strength", laser_strength)

            for sb in self.sb_results:
                sb[4] = (sb[3] / laser_strength[0]) * np.sqrt(
                    (sb[4] / sb[3]) ** 2 + (laser_strength[1] / laser_strength[0]) ** 2)
                sb[3] = sb[3] / laser_strength[0]
            for sb in list(self.full_dict.values()):
                sb[3] = (sb[2] / laser_strength[0]) * np.sqrt(
                    (sb[3] / sb[2]) ** 2 + (laser_strength[1] / laser_strength[0]) ** 2)
                sb[2] = sb[2] / laser_strength[0]
            self.parameters['normalized?'] = True

    def save_processing(self, file_name, folder_str, marker='', index=''):
        """
        This will save all of the self.proc_data and the results from the
        fitting of this individual file.

        Format:
        spectra_fname = file_name + '_' + marker + '_' + str(index) + '.txt'
        fit_fname = file_name + '_' + marker + '_' + str(index) + '_fits.txt'

        Inputs:
        file_name = the beginning of the file name to be saved
        folder_str = the location of the folder where the file will be saved,
                     will create the folder, if necessary.
        marker = I...I don't know what this was originally for
        index = used to keep these files from overwriting themselves when in a
                list

        Outputs:
        Two files:
            self.proc_data = the continuous spectrum
            self.sb_results = the individual sideband details

        :param file_name: The base name for the saved file
        :type file_name: str
        :param folder_str: The full name for the folder hte file is saved it.
                           Folder can be created
        :type folder_str: str
        :param marker: Marker for the file, appended to file_name, often the
                       self.parameters['series']
        :type marker: str
        :param index: used to keep these files from overwriting themselves when
                      marker is the same
        :type index: str or int
        :return: None
        """
        try:
            os.mkdir(folder_str)
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

        spectra_fname = file_name + '_' + marker + '_' + str(index) + '.txt'
        fit_fname = file_name + '_' + marker + '_' + str(index) + '_fits.txt'
        self.save_name = spectra_fname
        # self.parameters["files included"] = list(self.files)
        try:
            parameter_str = json.dumps(
                self.parameters, sort_keys=True, indent=4,
                separators=(',', ': ')
                )
        except Exception:
            print("Source: PMT.save_images\nJSON FAILED")
            print("Here is the dictionary that broke JSON:\n", self.parameters)
            return
        parameter_str = parameter_str.replace('\n', '\n#')

        # Make the number of lines constant so importing is easier
        # for num in range(99 - num_lines): parameter_str += '\n#'
        num_lines = parameter_str.count('#')
        parameter_str += '\n#' * (99 - num_lines)

        origin_import_spec = '\nNIR frequency,Signal,Standard error\neV,arb. u.,arb. u.\n,{:.3f},'.format(
            self.parameters["fieldStrength"]["mean"])
        spec_header = '#' + parameter_str + origin_import_spec

        origin_import_fits = '\nCenter energy,error,Amplitude,error,Linewidth,error\neV,,arb. u.,,eV,,\n,,'  # + marker
        fits_header = '#' + parameter_str + origin_import_fits

        for sideband in sorted(self.sb_dict.keys()):
            # TODO: REPLACE ALL INSTANCES OF ERRORS AS CONTROL STATEMENTS WITH
            #       CORRECT IF/ELSE OR SIMILAR LOGIC
            try:
                complete = np.vstack((complete, self.sb_dict[sideband]))
            except Exception:
                complete = np.array(self.sb_dict[sideband])

        np.savetxt(
            os.path.join(folder_str, spectra_fname), complete, delimiter=',',
            header=spec_header, comments='', fmt='%0.6e')

        try:
            np.savetxt(os.path.join(folder_str, fit_fname), self.sb_results,
                       delimiter=',',
                       header=fits_header, comments='', fmt='%0.6e')
        except AttributeError:
            # Catch the error that happens if you save something without files
            print("warning, couldn't save fit file (no sidebands found?)")

        print("Saved PMT spectrum.\nDirectory: {}".format(
            os.path.join(folder_str, spectra_fname)))