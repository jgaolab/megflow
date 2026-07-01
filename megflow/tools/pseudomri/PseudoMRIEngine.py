from copy import deepcopy
from pathlib import Path

import mne
import numpy as np
import nibabel as nib
from rich import print
from scipy import stats, linalg, spatial
from IsoScore import IsoScore
from mne.viz._3d import _fiducial_coords
from rich.progress import Progress
from mne.io.constants import FIFF
from nibabel.processing import resample_to_output


def PseudoMRIEngine(
    fname_info,
    pseudo_subj,
    dir_anat_pseudo,
    template_subj,
    dir_anat_templ,
    mirror_hsps=True,
    dense_surf=True,
    use_hpi=True,
    z_thres=0.02,
    wreg_est=0.000005,
    wreg_apply=0.00005,
    blocksize=500000,
    nmax_Ctrl=200,
    dig_reject_min_max=(2, 10),
):

    fname_info = Path(fname_info)

    dir_anat_templ = Path(dir_anat_templ)
    dir_anat_pseudo = Path(dir_anat_pseudo)

    template_dir = dir_anat_templ / "template"
    fname_src_mri = template_dir / f"{template_subj}-T1.mgz"
    fname_src_fid = template_dir / f"{template_subj}-fiducials.fif"
    fname_src_surf = template_dir / f"{template_subj}-outer_skin.surf"

    fname_warped_mri = dir_anat_pseudo / f"{pseudo_subj}.nii.gz"
    fname_warped_mri.parent.mkdir(parents=True, exist_ok=True)

    if fname_warped_mri.exists():
        return

    fids, hpis, hsps = find_plot_isotraks(fname_info)

    try:
        all_hsps = np.vstack((fids, np.vstack((hpis, hsps))))
        hpis_hsps = np.vstack((hpis, hsps)) if use_hpi else hsps
    except:
        all_hsps, hpis_hsps = hsps, hsps

    above_thrs = z_thres if dense_surf else 0.0
    _, trans_nm2ras = get_ras_to_neuromag_trans(fname_src_fid)
    _, fids_LNR, _ = get_fiducial_LNR(fname_src_fid)

    template_headsurf = mne.surface.read_surface(fname_src_surf, return_dict=True)[2]
    template_headsurf["rr"] /= 1000  # covert to meter
    template_headsurf["rr"] *= 0.975  # shrink inward to reduce mismatch

    surf2warp = deepcopy(template_headsurf)

    hpis_hsps_good = find_good_HSPs(
        hpis_hsps,
        surf2warp,
        fname_src_fid,
        above_thrs=above_thrs,
        min_rej_percent=dig_reject_min_max[0],
        max_rej_percent=dig_reject_min_max[1],
    )

    hpis_hsps_above_thrs = np.nonzero(hpis_hsps_good[:, 2] > -above_thrs)[0]
    hpis_hsps2warp = hpis_hsps_good[hpis_hsps_above_thrs, :]
    iso_val = IsoScore.IsoScore(hpis_hsps2warp.T)  # Uniformilty
    total_good_points = hpis_hsps2warp.shape[0] + 3

    print(f"Number of HSPs = {all_hsps.shape[0]}")
    print(f"Number of HSPs used = {total_good_points}")
    print(f"Iso_score = {iso_val:.2f}")

    hpis_hsps2warp_orig = np.empty((0, 3))

    apply_mirroring = mirror_hsps and hpis_hsps2warp.shape[0] < 40
    if apply_mirroring:
        print("Mirroring HSPs to make it denser...")
        hpis_hsps2warp_true = deepcopy(hpis_hsps2warp)
        hpis_hsps2warp_reflect = deepcopy(hpis_hsps2warp) * (-1, 1, 1)
        hpis_hsps2warp = np.vstack((hpis_hsps2warp_true, hpis_hsps2warp_reflect))

    # to avoid too dense points, downsample to 100-300 points only
    nmax_Ctrl = min(nmax_Ctrl - (3 + hpis_hsps2warp_orig.shape[0]), hpis_hsps2warp.shape[0])
    # Also, while using estimated dense HSPs, the original HSPs will be concatenated later
    selidx = np.linspace(0, hpis_hsps2warp.shape[0] - 1, nmax_Ctrl, dtype=int)
    hpis_hsps2warp = hpis_hsps2warp[selidx, :]

    # concatenating the original HSPs
    hpis_hsps2warp = np.vstack((hpis_hsps2warp_orig, hpis_hsps2warp))

    # concatenating the LPA, Nasian, and RPA
    all_hsps2warp = np.vstack((fids, hpis_hsps2warp))

    all_hsps = mne.transforms.apply_trans(trans_nm2ras, all_hsps, move=True)
    all_hsps2warp = mne.transforms.apply_trans(trans_nm2ras, all_hsps2warp, move=True)

    digpoints = deepcopy(all_hsps2warp)
    iso_score_final = IsoScore.IsoScore(
        deepcopy(all_hsps2warp).T if all_hsps2warp.shape[0] == 3 else deepcopy(all_hsps2warp)
    )

    print(f"The final number of HSP used for warping = {digpoints.shape[0]}")
    print(f"Iso_score = {iso_score_final:.2f}")

    # Compute warping transform
    # The three srcCtrl points for isotrak fids would be three MRI surface fids (from fiducial file)
    _, fids_LNR, _ = get_fiducial_LNR(fname_src_fid)
    srcCtrl_fids = deepcopy(fids_LNR)
    srcCtrl_fids_dist = get_all_to_all_point_dist(srcCtrl_fids, digpoints[:3])

    # find closed points for rest of the HSPs and compute distances
    mesh_pos = deepcopy(surf2warp["rr"])
    above_thrs_idx = np.nonzero(mesh_pos[:, 2] > (fids_LNR[:, 2].min() - above_thrs))[0]
    mesh_pos = mesh_pos[above_thrs_idx, :]

    closest_vert_pos_rest, closest_vert_idx_rest, closest_vert_dist_rest = (
        np.empty((0, 3)),
        np.empty((0, 1), dtype=int),
        np.empty((0, 1)),
    )
    for ii in range(3, digpoints.shape[0]):
        closest_vert_pos, idx, closest_vert_dist = find_closest_node_dist(
            digpoints[ii, :], mesh_pos, multipy2dist=1000
        )
        closest_vert_pos_rest = np.vstack((closest_vert_pos_rest, closest_vert_pos))
        closest_vert_idx_rest = np.vstack((closest_vert_idx_rest, idx))
        closest_vert_dist_rest = np.vstack((closest_vert_dist_rest, closest_vert_dist))

    # Append all for fids and hpi_hsp
    closest_vert_pos_all = np.vstack((srcCtrl_fids, closest_vert_pos_rest))
    closest_vert_dist_all = np.hstack((srcCtrl_fids_dist, closest_vert_dist_rest.flatten())).T
    print(
        f"DestCtrl to SrcCtrl min, mean, max dist. = {closest_vert_dist_all.min():.2f} mm, "
        f"{closest_vert_dist_all.mean():.2f} mm, {closest_vert_dist_all.max():.2f} mm"
    )
    srcCtrl = deepcopy(closest_vert_pos_all)  # source control points (p)
    destCtrl = deepcopy(digpoints)  # destination contrl points (q)

    print(
        f"Computing the warping transform using linear solver with {srcCtrl.shape[0]} source "
        f"and {destCtrl.shape[0]} destination control points (with regularization = {wreg_est})."
    )

    # Warp anatomy
    mne.utils.logger.info(f"Warping anatomy:  {template_subj} -> {pseudo_subj}")

    wdata, miscs = apply_warp_to_anatomy(
        deepcopy(srcCtrl),
        deepcopy(destCtrl),
        mridata=None,
        t1_fname=fname_src_mri,
        Torig=None,
        block_size=blocksize,
        reg=wreg_apply,
        reg_mode=2,
        resample=False,
        rs_voxel_sizes=[0.5, 0.5, 0.5],
    )

    if wdata is not None:
        warped_mri_affine = deepcopy(miscs["mriobj"].affine)
        warped_mri_header = deepcopy(miscs["mriobj"].header)

        mri_warped = nib.Nifti1Image(deepcopy(wdata), warped_mri_affine, warped_mri_header)
        nib.save(mri_warped, fname_warped_mri)
        crop_center_nii(fname_warped_mri, fname_warped_mri)

    print(f"Check results in -> {fname_warped_mri}")


def get_all_to_all_point_dist(vertices1, vertices2, unit_multiplier=1000):
    if vertices1.shape != vertices2.shape:
        # raise Exception('vertices1 and vertices2 are not of the same size.')
        print("NOTE: vertices1 and vertices2 are not of the same size.")
        print(f"len(vertices1) = {vertices1.shape[0]}, len(vertices2) = {vertices2.shape[0]}")
        vertices11 = vertices1 if vertices1.shape[0] < vertices2.shape[0] else vertices2
        vertices22 = vertices1 if vertices1.shape[0] > vertices2.shape[0] else vertices2
        one2one_dists = [
            np.sqrt(np.sum(np.square(vertices11[ii, :] - vertices22[ii, :])))
            for ii in range(vertices11.shape[0])
        ]
        one2one_dists = np.array(one2one_dists) * unit_multiplier
    else:
        one2one_dists = []
        for ii in range(vertices1.shape[0]):
            one2one_dists.append(np.sqrt(np.sum(np.square(vertices1[ii, :] - vertices2[ii, :]))))
        one2one_dists = np.array(one2one_dists) * unit_multiplier
    return one2one_dists


def sub2ind_matlab(siz, v1, v2, v3=None):
    numOfIndInput = 2 if v3 is None else 3
    ndx = np.double(v1)
    if numOfIndInput >= 2:
        ndx += (np.double(v2) - 1) * siz[0]
    if numOfIndInput == 3:
        k = np.cumprod(siz)
        v = v3
        ndx += (np.double(v) - 1) * k[1]
    return ndx


def find_closest_node(node, nodes):  # function to find closest points
    closest_index = spatial.distance.cdist([node], nodes).argmin()
    return nodes[closest_index], closest_index


def find_closest_node_dist(node, nodes, multipy2dist=1):  # function to find closest points
    closest_index = spatial.distance.cdist([node], nodes).argmin()
    closest_node = nodes[closest_index]
    diff = np.sqrt(np.sum(np.square(node - closest_node))) * multipy2dist
    return closest_node, closest_index, diff


def find_plot_isotraks(headshape_file, coord_frame="head"):
    # Read file contents
    try:
        info = mne.io.read_info(headshape_file)
    except Exception as e:
        print(e)
        digs_pts, coord_frame = mne.io.read_fiducials(headshape_file)
        info = {}
        info["dig"] = digs_pts
    # Find HPI, extras, and cardinal points locations
    hpi_loc = np.array([
        d["r"]
        for d in (info["dig"] or [])
        if (d["kind"] == FIFF.FIFFV_POINT_HPI and d["coord_frame"] == FIFF.FIFFV_COORD_HEAD)
    ])
    ext_loc = np.array([
        d["r"]
        for d in (info["dig"] or [])
        if (d["kind"] == FIFF.FIFFV_POINT_EXTRA and d["coord_frame"] == FIFF.FIFFV_COORD_HEAD)
    ])

    car_loc = _fiducial_coords(info["dig"], FIFF.FIFFV_COORD_HEAD)

    if coord_frame == "meg" and "dev_head_t" in info:
        for loc in (hpi_loc, ext_loc, car_loc):
            loc[:] = mne.transforms.apply_trans(
                mne.transforms.invert_transform(info["dev_head_t"]), loc
            )

    if len(car_loc) == len(ext_loc) == len(hpi_loc) == 0:
        print("Digitization points not found. Cannot plot digitization.")
        return None

    return car_loc, hpi_loc, ext_loc


def get_ras_to_neuromag_trans(fiducial_file):
    fiducials = mne.io.read_fiducials(fiducial_file)
    fid_labels = ["LPA", "Nas", "RPA"]
    fiducials_m = {}
    for ii in range(3):
        fiducials_m[fid_labels[ii]] = fiducials[0][ii]["r"]
    trans_ras2neuromag = mne.transforms.get_ras_to_neuromag_trans(
        fiducials_m["Nas"].flatten(), fiducials_m["LPA"].flatten(), fiducials_m["RPA"].flatten()
    )
    trans_neuromag2ras = linalg.inv(deepcopy(trans_ras2neuromag))
    return trans_ras2neuromag, trans_neuromag2ras


def get_fiducial_LNR(fiducial_file):
    fids_ras = mne.io.read_fiducials(fiducial_file)[0]
    labels = ["", "LPA", "Nasion", "RPA"]
    fids_LNR, fids_LNR_dict = np.empty((0, 3)), {}
    for fiff_id in [1, 2, 3]:
        for d in fids_ras:
            if d["ident"] == fiff_id:
                fids_LNR = np.vstack((fids_LNR, dict(d.items())["r"]))
                fids_LNR_dict[labels[fiff_id]] = dict(d.items())["r"]
    return fids_ras, fids_LNR, fids_LNR_dict


def find_uni_scaler_for_min_dist(points1, points2, n_iter=200, mode="dist_sum"):
    points1_rphitheta = mne.transforms._cart_to_sph(points1)
    points2_rphitheta = mne.transforms._cart_to_sph(points2)
    points1_r = deepcopy(points1_rphitheta[:, 0])
    points2_r = deepcopy(points2_rphitheta[:, 0])

    dist_total, multipliers = [], []
    if mode == "dist_sum":
        mult = 1
        for _ in range(n_iter):  # increasing multiplyer
            mult *= 0.99
            dist_total.append((points1_r - (deepcopy(points2_r) * mult)).sum())
            multipliers.append(mult)
        mult = 1
        for _ in range(n_iter):  # decreasing multiplyer
            mult *= 1.01
            dist_total.append((points1_r - (deepcopy(points2_r) * mult)).sum())
            multipliers.append(mult)
        dist_total = np.array(np.abs(dist_total))
        mindist_idx = dist_total.argmin()
        mult_mindist = multipliers[mindist_idx]

    elif mode == "dist_mean":
        mult = 1
        for _ in range(n_iter):  # increasing multiplyer
            mult *= 0.99
            dist_total.append((points1_r - (deepcopy(points2_r) * mult)).mean())
            multipliers.append(mult)
        mult = 1
        for _ in range(n_iter):  # decreasing multiplyer
            mult *= 1.01
            dist_total.append((points1_r - (deepcopy(points2_r) * mult)).mean())
            multipliers.append(mult)
        dist_total = np.array(np.abs(dist_total))
        mindist_idx = dist_total.argmin()
        mult_mindist = multipliers[mindist_idx]

    elif mode == "ttest":
        mult = 1
        for _ in range(n_iter):  # increasing multiplyer
            mult *= 0.99
            dist_total.append(points1_r - (deepcopy(points2_r) * mult))
            multipliers.append(mult)
        mult = 1
        for _ in range(n_iter):  # decreasing multiplyer
            mult *= 1.01
            dist_total.append(points1_r - (deepcopy(points2_r) * mult))
            multipliers.append(mult)
        dist_total = np.array(np.abs(dist_total)).T
        tstat_all, t_pvalue_all = [], []
        for ii in range(len(multipliers)):
            ref_dist = np.random.uniform(low=0.0, high=1, size=(len(dist_total[:, ii]),))
            tstat, t_pvalue = stats.ttest_ind(ref_dist, dist_total[:, ii])
            tstat_all.append(tstat)
            t_pvalue_all.append(t_pvalue)
        best_similar_idx = np.array(t_pvalue).argmax()
        mult_mindist = multipliers[best_similar_idx]

    return mult_mindist


def find_good_HSPs(
    hpis_hsps, surf2warp, fiducial_file, above_thrs=0.02, min_rej_percent=2, max_rej_percent=10
):
    n_min_rej_hsp = np.ceil(hpis_hsps.shape[0] * min_rej_percent / 100).astype(int)
    n_max_rej_hsp = np.ceil(hpis_hsps.shape[0] * max_rej_percent / 100).astype(int)

    trans_ras2neuromag, trans_neuromag2ras = get_ras_to_neuromag_trans(fiducial_file)
    _, fids_LNR, _ = get_fiducial_LNR(fiducial_file)
    hpis_hsps_ras = mne.transforms.apply_trans(
        trans_neuromag2ras, deepcopy(hpis_hsps), move=True
    )  # convert in RAS
    zlim = fids_LNR[:, 2].min() - above_thrs
    point_set1 = deepcopy(
        hpis_hsps_ras[hpis_hsps_ras[:, 2] >= zlim, :]
    )  # Limit hpis_hsps_ras above zlim
    surf_pos = surf2warp["rr"][surf2warp["rr"][:, 2] >= zlim, :]  # Limit headsurf above zlim
    point_set2 = surf_pos[mne.surface._DistanceQuery(surf_pos).query(point_set1)[1], :]
    mult_mindist = find_uni_scaler_for_min_dist(point_set1, point_set2, n_iter=200, mode="dist_sum")
    point_set2_scaled = point_set2 * mult_mindist

    point_set1_rphitheta = mne.transforms._cart_to_sph(point_set1)
    point_set2_rphitheta = mne.transforms._cart_to_sph(point_set2)
    outward_hsp_idx = np.nonzero(point_set1_rphitheta[:, 0] > point_set2_rphitheta[:, 0])[0]
    point_set2_scaled_rphitheta = mne.transforms._cart_to_sph(point_set2_scaled)

    outward_hsp_percentage = (len(outward_hsp_idx) * 100) / len(point_set1)
    all_dists = (
        np.abs(point_set1_rphitheta[:, 0] - point_set2_scaled_rphitheta[:, 0]) * 1000
    )  # in mm

    if outward_hsp_percentage == 0 and all_dists.max() < 20.0:
        reject_idx = np.array([], int)
    else:
        """ find outliers """
        Q1 = np.percentile(all_dists, 25, method="midpoint")
        Q3 = np.percentile(all_dists, 75, method="midpoint")
        IQR = Q3 - Q1
        extremes_idx = np.nonzero(all_dists > (Q3 + 3.0 * IQR))[0]
        outlrs_indx = np.nonzero(all_dists > (Q3 + 1.5 * IQR))[0]
        rej_idx = np.array(extremes_idx.tolist() + outlrs_indx.tolist())

        if len(rej_idx) == 0:
            reject_idx = all_dists.argsort(axis=None)[::-1][:n_min_rej_hsp]

        elif len(rej_idx) > 0 and len(rej_idx) < n_min_rej_hsp:
            reject_idx1 = rej_idx
            reject_idx2 = all_dists.argsort(axis=None)[::-1][:n_min_rej_hsp]
            reject_idx = np.union1d(reject_idx1, reject_idx2).astype(int)

        elif len(extremes_idx) >= n_max_rej_hsp:
            reject_idx = extremes_idx
        elif len(rej_idx) >= n_max_rej_hsp:
            reject_idx = np.array(extremes_idx.tolist() + outlrs_indx.tolist())
        else:
            reject_idx = all_dists.argsort(axis=None)[::-1][:n_min_rej_hsp]

    reject_idx = np.unique(reject_idx.astype(int))
    good_hpis_hsps_ras = np.delete(point_set1, reject_idx, axis=0)

    print(f"Total number of good points = {len(good_hpis_hsps_ras)}")
    good_hpis_hsps = mne.transforms.apply_trans(
        trans_ras2neuromag, deepcopy(good_hpis_hsps_ras), move=True
    )  # convert back to NM
    return good_hpis_hsps


def crop_center_nii(input_path, output_path, crop_size=(255, 255, 255)):
    img = nib.load(input_path)
    data = img.get_fdata()
    affine = img.affine
    x, y, z = data.shape[:3]
    cx, cy, cz = crop_size
    startx = (x - cx) // 2
    starty = (y - cy) // 2
    startz = (z - cz) // 2

    cropped = data[startx : startx + cx, starty : starty + cy, startz : startz + cz]

    new_affine = affine.copy()
    shift = np.array([(x - cx) / 2, (y - cy) / 2, (z - cz) / 2, 0])
    new_affine[:, 3] = affine @ shift

    cropped_img = nib.Nifti1Image(cropped, affine, img.header)
    nib.save(cropped_img, output_path)


def my_warp3d_trans(p, q, reg=1e-3, reg_mode=2, comment="", wtol=1e-06, return_reg=False):
    N = p.shape[0]
    px = np.tile(p[:, 0].reshape((p[:, 0].shape[0], 1)), (1, N))
    py = np.tile(p[:, 1].reshape((p[:, 1].shape[0], 1)), (1, N))
    pz = np.tile(p[:, 2].reshape((p[:, 2].shape[0], 1)), (1, N))
    K = np.sqrt((px - px.T) ** 2 + (py - py.T) ** 2 + (pz - pz.T) ** 2)
    P = np.hstack((p, np.ones((N, 1))))
    L = np.vstack([np.hstack([K, P]), np.hstack([P.T, np.zeros((4, 4))])])
    D = np.concatenate((q - p, np.zeros((4, 3))), axis=0)
    if reg_mode == 1:
        try:
            H = linalg.solve(L, D, check_finite=True, assume_a="gen", transposed=False)
        except linalg.LinAlgError:
            L += reg * np.eye(L.shape[0])
            H = linalg.solve(L, D, check_finite=True, assume_a="gen", transposed=False)
    else:
        try:
            H = linalg.solve(L, D, check_finite=True, assume_a="gen", transposed=False)
        except linalg.LinAlgError:
            print(f"Using regularization = {reg}")
            L += reg * np.eye(L.shape[0])
            H = linalg.solve(L, D, check_finite=True, assume_a="gen", transposed=False)
        while any((np.dot(L, H) - D).flatten() >= wtol):  # changed on 13/05/2022
            print(f"Using regularization = {reg}")
            L += reg * np.eye(L.shape[0])
            H = linalg.solve(L, D, check_finite=True, assume_a="gen", transposed=False)
            reg *= 10
    if (np.isnan(H)).any():
        H = linalg.pinv(L) * D
    W = H[:N, :]
    A = H[N:, :]
    e = np.sum(np.diag(np.dot(W.T, np.dot(K, W))))
    print(f"{comment} Bending energy = {e} (reg = {reg})")
    if return_reg:
        return W, A, e, reg
    return W, A, e


def my_warp_src(r, A, W, p):
    rw = np.dot(r, A[:3, :3])
    rw += A[3, :]
    n_p = p.shape[0]
    U = np.sqrt(
        ((np.tile(r[:, 0].reshape((r[:, 0].shape[0], 1)), (1, n_p)) - p[:, 0].T) ** 2)
        + ((np.tile(r[:, 1].reshape((r[:, 1].shape[0], 1)), (1, n_p)) - p[:, 1].T) ** 2)
        + ((np.tile(r[:, 2].reshape((r[:, 2].shape[0], 1)), (1, n_p)) - p[:, 2].T) ** 2)
    )
    rw += np.dot(U, W)
    return rw


def apply_warp_to_anatomy(
    srcPts,
    destPts,
    mridata,
    t1_fname=None,
    Torig=None,
    block_size=1000000,
    reg=0.00005,
    reg_mode=1,
    resample=False,
    rs_voxel_sizes=None,
):
    if rs_voxel_sizes is None:
        rs_voxel_sizes = [0.5, 0.5, 0.5]
    if mridata is None or Torig is None:
        t1 = nib.load(t1_fname)
        if resample:
            print("Note: Applying resampling....")
            t1_res = resample_to_output(
                deepcopy(t1),
                voxel_sizes=rs_voxel_sizes,
                out_class=nib.freesurfer.mghformat.MGHImage,
            )
            del t1
            t1 = t1_res

        data = np.asarray(t1.dataobj)
        mgh = nib.MGHImage(t1.dataobj, t1.affine)
        vox2ras_tkr = mgh.header.get_vox2ras_tkr()
        Torig = vox2ras_tkr
        vox2ras_tkr_inv = np.linalg.inv(vox2ras_tkr)
        Torig_inv = vox2ras_tkr_inv
        miscs = {}
        miscs["mriobj"] = t1
        miscs["Torig"] = Torig
        miscs["Torig_inv"] = Torig_inv
        miscs["original_anat"] = data
    else:
        data = deepcopy(mridata)
        miscs = {}
    print(f"Data dimensions = {data.shape}")

    srcPts_vox = mne.transforms.apply_trans(np.linalg.inv(Torig), srcPts * 1000)
    destPts_vox = mne.transforms.apply_trans(np.linalg.inv(Torig), destPts * 1000)
    _, _, e_vox, regWtransVox = my_warp3d_trans(
        srcPts_vox,
        destPts_vox,
        reg=reg,
        reg_mode=reg_mode,
        comment="Estimating Wtrans for vox..",
        return_reg=True,
    )
    W_vox_inv, A_vox_inv, e_vox_inv, reginvWtransVox = my_warp3d_trans(
        destPts_vox,
        srcPts_vox,
        reg=reg,
        reg_mode=reg_mode,
        comment="Estimating inv. Wtrans for vox..",
        return_reg=True,
    )
    miscs["e_vox"] = e_vox
    miscs["e_vox_inv"] = e_vox_inv
    miscs["regWtransVox"] = regWtransVox
    miscs["reginvWtransVox"] = reginvWtransVox

    if len(data.shape) > 3:
        print("====> Omitting, not implemented for 4D data.")
        newCube = None
    else:
        sizeMri = data.shape
        newCube = np.ones(sizeMri)
        nVoxels = data.size
        BLOCK_SIZE = block_size
        nBlocks = int(np.ceil(nVoxels / BLOCK_SIZE))
        ix0 = 0

        with Progress() as prog:
            task = prog.add_task("[cyan]Processing...", total=nBlocks)
            for _ in range(nBlocks):
                ix1 = min(ix0 - 0 + BLOCK_SIZE, nVoxels)
                xv, yv, zv = np.unravel_index(np.arange(ix0, ix1), sizeMri, order="F")
                rv = np.vstack((np.vstack((xv, yv)), zv)).T
                rv_inv = my_warp_src(rv, A_vox_inv, W_vox_inv, destPts_vox) + rv
                rv_inv = np.round(rv_inv)
                iOutside = np.nonzero(
                    np.sum(
                        np.logical_or(
                            (rv_inv < 0),
                            (rv_inv > np.tile(np.array(sizeMri) - 1, (rv_inv.shape[0], 1))),
                        ),
                        axis=1,
                    )
                    > 0
                )[0]
                rv_inv[iOutside, :] = 1
                rv_inv = rv_inv.astype(int)
                ix_inv = sub2ind_matlab(
                    sizeMri, rv_inv[:, 0], rv_inv[:, 1], v3=rv_inv[:, 2]
                ).astype(int)
                newCube = newCube.flatten("F")
                newCube[np.arange(ix0, ix1)] = data.copy().flatten("F")[ix_inv]
                newCube = newCube.reshape(sizeMri, order="F")
                newCube = newCube.flatten("F")
                newCube[iOutside] = 0
                newCube = newCube.reshape(sizeMri, order="F")
                ix0 = ix1
                prog.update(task, advance=1)

    return newCube, miscs
