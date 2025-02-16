import matplotlib.pyplot as plt
from hparams.get_config import Config



def heatmap_drawing(score_tensor, 
                    save_path=None,
                    title=None,
                    xlabel=None,
                    ylabel=None,
                    xticks=None
                    ):
    plt.clf()
    score_copy = score_tensor.clone().to('cpu')
    plt.imshow(score_copy, cmap='coolwarm', interpolation='nearest')
    plt.colorbar()  #
    plt.title(title or "Neuron Cluster Scores")
    plt.xlabel(xlabel or "Position")
    plt.ylabel(ylabel or "Layer")
    plt.show()
    if save_path is not None:
        plt.savefig(save_path, dpi=300, format="jpg", bbox_inches="tight")



