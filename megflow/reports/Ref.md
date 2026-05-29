$ streamlit run reports.py

$ nextflow run meg_pipeline.nf -preview -with-dag workflow.png
$ nextflow run meg_pipeline.nf -preview -with-dag workflow.svg

Docker run
$ docker run --rm -it -p 8501:8501 -v /data/liaopan/datasets/SMN4Lang/g:/output -v /data/liaopan/datasets/SMN4Lang/smri:/smri megflow:0.0.3 -r

Docker output ownership is handled by the entrypoint: it prepares mounted
output permissions as root, then drops to the host UID/GID inferred from
`/input` when available. Report-only runs that only mount `/output` infer
ownership from `/output`. Use `-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`
when the owner should be specified explicitly.

https://www.nextflow.io/docs/latest/reports.html#workflow-diagram
sudo apt install graphviz
sudo yum install graphviz


https://mne.tools/stable/auto_tutorials/intro/70_report.html
MNE-reports Ref.
MEG-Reports

Raw:
- Info
- PSD

ArtifactsDetection
- bad channels
- bad segments
- detection & repaired visualization

Events:
- Events plot

Epochs:
- Info
- Meta Info
- EPR image
- PSD

Evoked:
- INFO
- Time Course
- Topographies
- Global Field Power
- Whitened plot

Covariance
- Covariance matrix
- Singular values

Projectors ?

ICA:
- ICA Info
- Original and Cleaned Signal
- Scores for matching EOG patterns
- Original and cleaned EOG epochs
- ICA component properties

MRI with BEM:
- BEM plot|BEM visualizations
https://mne.tools/stable/auto_examples/inverse/mixed_source_space_inverse.html 
- plot bem 

Coregistration:
- coregistration plot(sensors and MRI)
_plot_head_shape_points 中 opcity的不透明度修改：
-  vi /home/liaopan/anaconda3/envs/megflow/lib/python3.12/site-packages/mne/viz/_3d.py
- opcity=1

Forward solution:
- Info or plot?
- Lead Field vectors plot based on MRI(surface)

InverseOperator:
- Info and plot?

SourceEstimate:
- source plot
- pip install stpyvista | https://github.com/edsaac/stpyvista | 支持3D可视化交互演示

###########################
MRI-Reports

recon-all visualization:
- surface visualization?
- Brain volume segmention??
- Cortical mesh parcellation??

source space:
- visualization
- check

BEM:
- watershed bem plot
- check topology and surface file(.surf)
- single shpere or overspheres visual?
- Innerskull \outterskull\

https://mne.tools/stable/auto_tutorials/forward/10_background_freesurfer.html#sphx-glr-auto-tutorials-forward-10-background-freesurfer-py

https://mne.tools/stable/auto_examples/inverse/morph_surface_stc.html#ex-morph-surface morph or smooth


https://brainspace.readthedocs.io/en/latest/pages/getting_started.html
BrainSpace
###################
