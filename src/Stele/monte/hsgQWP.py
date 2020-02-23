from . import hsg
import numpy as np

"""
Functions and objects to be included here are
qwp.expFanCompiler
    qwp.expFanCompiler.addSet
    qwp.expFanCompiler.build
    qwp.expFanCompiler.buildAndSave
    qwp.expFanCompiler.FanCompiler
qwp.extractMatrices.findJ
qwp.extractMatrices.saveT
"""

class FanCompiler(object):
    """
    Helper class for compiling the data of a polarimetry NIR alpha sweep.
    This class helps to normalize the datasets: it will make sure each slice of
    a different NIR_alpha has the same sideband orders, preventing issues when not all
    data sets saw the same number of orders.

    Typical use scenario:

    datasets = [ ... list of folders, each being a dataset of different NIR alphas ...]
    outputs = FanComilier(<whatever sideband orders you want compiled>)
    for data in datasets:
        laserParams, rawData = hsg.hsg_combine_qwp_sweep(folder, save=False, verbose=False)
        _, fitDict = hsg.proc_n_fit_qwp_data(rawData, laserParams, vertAnaDir="VAna" in folder,
                                        series=folder)
        outputs.addSet(nira, fitDict)

    outputs.buildAndSave(fname)

    This is put together in the static method, fromDataFolder, where you pass the
    folder which contains the folders of polarimetry data

    build() will return a dictionary where each key is a diferent angle parameter
    The values of the dict are the 2D datasets from polarimetry

    """
    def __init__(self, wantedSBs, keepErrors = False, negateNIR = True):
        """

        :param wantedSBs:
        :param keepErrors: Whether the errors in the angles/values are kept inthe
            data sets or not. Defaults to false because they are often not used (this
            class getting passed to FanDiagrams and such)
        :param negateNIR: flag for whether to negate the NIR alpha value. Currently,
        this is done because the PAX views -z direction, while home-built views +z (
        with NIR)
        """
        self.want = np.array(wantedSBs)

        # I guess you could make this a kwarg to the class and pass it, but
        # I don't think it really matters here
        keys = [ "S0", "S1", "S2", "S3", "alpha", "gamma", "DOP"]

        # Keep an array for each of the datasets directly
        self.outputArrays = {ii: wantedSBs.reshape(-1, 1) for ii in keys}

        # Keep track of the NIR alpha/gamma's which are provided to the compiler
        self.nirAlphas = []
        self.nirGammas = []
        # A flag used when loading data to determine whether or not to keep the
        # errors along
        self._e = keepErrors

        # Flag for whether the NIR alphas should be negated or not. It prints an error
        # as it seemed like a bad thing to need to arbitrarily negate an angle,
        # before it was realized the PAX and polarimeter measure different reference
        # frames
        self._n = 1
        if negateNIR:
            print("WARNING: NEGATING NIR ALPHA")
            self._n = -1

    @staticmethod
    def fromDataFolder(folder, wantedSBs, keepErrors = False, negateNIR = True,
                       eta=None, doNorms = False):
        """
        Create a fan compiler by passing the data path. Handles looping through the
        folder's sub-folders to find
        :param folder: The folder to search through. Alternatively, if it's a
        list/iterable, iterate through that instead. Useful if external code is
        directly removing sets of data.
        :return:
        """
        comp = FanCompiler(wantedSBs, keepErrors, negateNIR)
        # If it's a string, assume it's a single path that wants to be searached
        if isinstance(folder, str):
            wantFolders = hsg.natural_glob(folder, "*")
        else:
            # Otherwise, assume they've passed an iterable to search through
            wantFolders = folder


        for nirFolder in wantFolders:
            # Provide ways to skip over data sets by mis-naming/flagging them
            if "skip" in nirFolder.lower() or "bad" in nirFolder.lower(): continue
            laserParams, rawData = hsg.hsg_combine_qwp_sweep(nirFolder, save=False,
                                                             verbose=False,
                                                             loadNorm=doNorms)

            _, fitDict = hsg.proc_n_fit_qwp_data(rawData, laserParams,
                                                 vertAnaDir="VAna" in nirFolder,
                                                 series=nirFolder,
                                                 eta=eta)
            comp.addSet(fitDict)
        return comp

    def addSet(self, dataSet):
        """ Assume it's passed from  proc_n_fit_qwp_data, assuming it is a dict
        with the keys and shape returned by that function"""

        # Keeps track of all the new data passed. Keys are the angles/S parameters,
        # values are arrays for each of those which will contain the value of the
        # parameters for a given sideband order
        newData = {ii: [] for ii in self.outputArrays}

        # new data needs to parsed to extract the relevant parameters for all
        # the sidebands specified in this FanCompiler's constructor. Data is kept as
        # a list of lists in `newData`


        if self._e:
            # keep track of the errors in everything
            nirAlpha = [self._n*dataSet["alpha"][0][1], dataSet["alpha"][0][2]]
            nirGamma = [dataSet["gamma"][0][1], dataSet["gamma"][0][2]]
            for sb in self.want:
                # the list(*[]) bullshit is to make sure a list gets appended,
                # not a numpy array. Further complicated because if the list
                # comprehension returns nothing, it doesn't append anything,
                # hence casting to a list to enforce an empty list gets appended.
                [jj.append( list(*[ii[1:] for ii in dataSet[kk] if ii[0] == sb]) )
                 for kk, jj in newData.items()]
                if not newData["alpha"][-1]:
                    # no data was found, so the last element is an empty array.
                    # Force it to have elements with the same dimensions so it
                    # won't break numpy analysis below
                    for jj in newData.values():
                        jj[-1] = [np.nan, np.nan]
        else:
            # Even though it's a single number each, put them in lists so they can
            # be list.extended() and consistent with the error usage above
            nirAlpha = [self._n*dataSet["alpha"][0][1]]
            nirGamma = [dataSet["gamma"][0][1]]
            for sb in self.want:
                # Even though only one element is being kept (i.e. data without error),
                # it's still being placed inside a list to be consistent with the
                # use case with errors above
                [jj.append( list([ii[1] for ii in dataSet[kk] if ii[0] == sb]) )
                 for kk, jj in newData.items()]
                if not newData["alpha"][-1]: # no data was found.
                    for jj in newData.values():
                        jj[-1] = [np.nan]

        for k, v in newData.items():
            self.outputArrays[k] = np.column_stack((self.outputArrays[k], v))


        # extending created lists accounts for keeping errors r not
        self.nirAlphas.extend(nirAlpha)
        self.nirGammas.extend(nirGamma)

    def build(self, withErrors = True):
        """
        Return only alpha, gamma, S0 parameters directly, for compatibility and ease.
        :param withErrors:
        :return:
        """
        data = self.buildAll()
        if not self._e:
            # You didn't keep track of errors when loading datasets, so just return
            # the data sets
            return data["alpha"], data["gamma"], data["S0"]

        if withErrors:
            return data["alpha"], data["gamma"], data["S0"]
        alphaData = np.column_stack((data["alpha"][:, 0], data["alpha"][:, 1::2]))
        gammaData = np.column_stack((data["gamma"][:, 0], data["gamma"][:, 1::2]))
        S0Data = np.column_stack((data["S0"][:, 0], data["S0"][:, 1::2]))
        return alphaData, gammaData, S0Data


    def buildAll(self):
        """
        a dict of d[<S0,S1,S2,S3,alpha, gamma, DOP>] where each item is a 2D array:

                 -1  |   NIRa   |   dNIR err  |  NIRa2   |  dNIRa err  |    ...
              sb1    | SB Data  | SB Data err | SB Data  | SB Data err |    ...
              sb2    |   ...    |     ...     |
              .
              .

        where "SB Data" is the data corresponding to the key of the dict.

        Errors are not included if not passed in the fanCompiler constructor

        return["gamma"] replaces the first row with the NIR gamma values, which was
        useful when doing polarimetry with non-linearly polarized light (i.e. circular)
        Furthermore, these values get passed to the Jones matrix extraction stuff

        :return:
        """
        fullData = {ii: np.append([-1], self.nirAlphas) for ii in
                    self.outputArrays.keys()}

        for k, v in self.outputArrays.items():
            fullData[k] = np.row_stack((fullData[k], v))

        # insert the gamma values into that array for the NIR laser
        fullData["gamma"][0, 1:] = self.nirGammas
        return fullData

    def buildAndSave(self, fname, *args, saveStokes=False):
        """
        fname: filename to save to. Must have a least one string formatter position
        to allow for saving separate alpha/gamma/s0 files. *args are passed to any
        other formatting positions.
        :param fname:
        :param args:
        :param saveStokes: Pass true if you want to save the stokes files
        :return:
        """

        if os.path.dirname(fname) and not os.path.exists(os.path.dirname(fname)):
            os.mkdir(os.path.dirname(fname))

        oh = "#\n" * 100
        oh += "\n\n"

        fullDataA, fullDataG, fullDataS = self.build()

        outputs = self.buildAll()

        if saveStokes:
            saveEms = [ii for ii in outputs.keys()]
        else:
            saveEms = ["alpha", "gamma", "S0"]

        for saveEm in saveEms:
            np.savetxt(fname.format(saveEm, *args), outputs[saveEm], header=oh,
                       delimiter=',',
                       comments='')

        # # fullData = np.append([-1], self.nirAlphas)
        # # fullData = np.row_stack((fullData, self.arrA))
        # np.savetxt(fname.format("alpha", *args), fullDataA, header=oh, delimiter=',',
        #            comments='')
        #
        # # fullData = np.append([-1], self.nirAlphas)
        # # fullData = np.row_stack((fullData, self.arrG))
        # np.savetxt(fname.format("gamma", *args), fullDataG, header=oh, delimiter=',',
        #            comments='')
        #
        # # fullData = np.append([-1], self.nirAlphas)
        # # fullData = np.row_stack((fullData, self.arrS))
        # np.savetxt(fname.format("S0", *args), fullDataS, header=oh, delimiter=',',
        #            comments='')

def findJ(alphas, gammas=None, **kwargs):
    """
    Extract the Jones matrix (x/y basis) from given data.
    alphas/gammas should be the matrices saved from the FanCompiler, of form:

    arb     | niralpha1 | niralpha2 | niralpha3 | niralpha4 | ...
    1st sb  | 1sb alpha | 1sb alpha |     .
    2nd sb  | 2sb alpha | 2sb alpha |     .
    3rd sb  | 3sb alpha | 3sb alpha |     .
      .
      .
      .

    Assumes both alphas/gammas are the same shape

    kwarg options:
       returnFlat-- return a flattened (Nx9) Jones matrix, of form
         [[sb#, Re(Jxx), Re(Jxy), Re(Jyx), Re(Jyy), Im(Jxx), Im(Jxy), Im(Jyx), Im(Jyy)],
          [  .. ]
          ]
        useful for saving to file.
        If false, return an 2x2xN,
          [[[Jxx, Jxy],
            [Jyx, Jyy]],
            [[ .. ]]
          ]
        useful for continuing into processing (and JonesVector maths).

        NOTE: You probably shouldn't use the "Return Flat" argument for saving.
        Instead, get the J matrix back and use saveT() to avoid accidentally
        introducing errors from difference in the order of the columns of the flattened
        matrix in this function vs saveT/loadT

    You can also just pass a FanCompiler object and it'll pull the alpha/gamma from
    that.

    :return:
    """

    defaults = {
        "returnFlat": False
    }
    defaults.update(kwargs)

    if gammas is None and isinstance(alphas, FanCompiler):
        alphas, gammas, _ = alphas.build(withErrors=False)

    sbs = alphas[1:,0]
    nirAlphas = alphas[0, 1:]
    nirGammas = gammas[0, 1:]
    # This SbStateGetter makes it more convenient to get the alpha and gamma
    # angles for a specific sideband and NIR alpha
    sbGetter = SbStateGetter(alphas[1:, 1:], gammas[1:, 1:], sbs, nirAlphas)

    ## Initialize the matrices
    outputFlatJMatrix = np.empty((len(sbs),9))
    outputJMatrix = np.empty((2, 2, len(sbs)), dtype=complex)

    # There's one J matrix for each sideband order, so naturally have to iterate over
    # each sideband
    for idx, sb in enumerate(sbs):
        # Get the list of alpha and gamma angles for each of the NIR Alphas used
        als, gms = zip(*[sbGetter(sb, ii) for ii in nirAlphas])
        # Check to make sure all of the data is reasonable (not nan, meaning the sideband
        # wasn't observed for all NIRalpha, or infinite when the fits fucked up)
        # Leaving these in causes issues for the minimizer, so they have to be skipped
        if not any(np.isfinite(als)) or not any(np.isfinite(gms)):
            # Do some python magic so I can still use p.x further and not have to
            # wrap everything in a try/except
            p = type("_", (object, ), {"x": np.array([np.nan]*3 + [0]*3)})
        else:
            sbJones = JV(alpha=als, gamma=gms)
            nirJones = JV(alpha=nirAlphas, gamma=nirGammas)
            # Note: We current'y don't do error propagation at this step
            costfunc = lambda jmatrix: np.linalg.norm(solver([nirJones, sbJones], jmatrix))

            p = minimize(costfunc, x0=np.ones(6))
        J = unflattenJ(p.x)
        outputJMatrix[..., idx] = J

        outputFlatJMatrix[idx] = np.array([sb, 1] # Re(Jxx) === 1
                                          + p.x[:3].tolist() # Re(Jxy-Jyy)
                                          + [0]  # Im(Jxx) === 0
                                          + p.x[3:].tolist() # Im(Jxy-Jyy)
                                          )

    if defaults["returnFlat"]: return outputFlatJMatrix
    return outputJMatrix


def saveT(T, sbs, out):
    """
    Save a complex T matrix, input as an Nx2x2, into a text file. Dumps it as a CSV
    where the first four columns are the real components, the last four are imaginary
    :param T:
    :param out:
    :return:
    """
    T = np.array(T.transpose(2, 0, 1))

    ## I'm nervous of trusting how numpy handles .view() on complex types. I feel like
    # I've seen it swap orders or something, where I've had to change the loadT function
    # to compensate. I guess when in doubt, process data from scratch, save it and
    # reload it and make sure the memory and disk matrices agree.

    # 01/04/19 No, fuck this. I don't trust view at all. I'm looking at two different
    # T matrices, and in one instance this gets reordered as
    #     ReT++,ReT+-,ReT-+,ReT--,ImT++,ImT+-,ImT-+,ImT--
    # while in another, it does it as
    #     ReT++,ImT++,ReT+-,ImT+-,ReT-+,ImT-+,ReT--,ImT--
    #
    # I have no fucking clue why it does it that way, but I'm sick and fucking tired of it
    # So no more
    #
    # flatT = T.reshape(-1, 4).view(float).reshape(-1, 8)

    flatT = T.reshape(-1, 4)
    flatT = np.column_stack((flatT.real, flatT.imag))

    # I'm also going to complicate this, because I want to save it like qile's matlab
    # code save his files, so that we can use the same loading.
    # As of 12/19/18, I believe the above code should be ordering columns as,

    ###   0    1     2     3      4     5    6     7
    ### ReT++,ReT+-,ReT-+,ReT--,ImT++,ImT+-,ImT-+,ImT--

    # Qile saves as
    ###   0    1     2     3      4     5    6     7
    ### ReT--,ImT--,ReT+-,ImT+-,ReT-+,ImT-+,ReT++,ImT++

    reorder = [ 3, 7, 1, 5, 2, 6, 0, 4 ]

    flatT = flatT[:, reorder]



    flatT = np.column_stack((sbs, flatT))

    header = "SB,ReT++,ImT++,ReT+-,ImT+-,ReT-+,ImT-+,ReT--,ImT--"
    header = "SB,ReT++,ReT+-,ReT-+,ReT--,Im++,Im+-,Im-+,Im--"

    header = "SB,ReT--,ImT--,ReT+-,ImT+-,ReT-+,ImT-+,ReT++,ImT++"
    np.savetxt(out,
               flatT, header=header, comments='', delimiter=',',
               fmt="%.6f")
    print("saved {}\n".format(out))
