"""
Reproduce Omniglot results of Snell et al Prototypical networks.
"""
import torch
from torch.optim import Adam
from torch.utils.data import DataLoader
import argparse

from voicemap.datasets import OmniglotDataset, MiniImageNet
from voicemap.models import get_few_shot_encoder
from voicemap.few_shot import NShotWrapper, proto_net_episode, EvaluateFewShot, prepare_nshot_task
from voicemap.train import fit
from voicemap.callbacks import *
from config import PATH


assert torch.cuda.is_available()
device = torch.device('cuda')
torch.backends.cudnn.benchmark = True


##############
# Parameters #
##############
parser = argparse.ArgumentParser()
parser.add_argument('--dataset')
parser.add_argument('--n-train', default=1)
parser.add_argument('--n-test', default=1)
parser.add_argument('--k-train', default=30)
parser.add_argument('--k-test', default=5)
parser.add_argument('--q-train', default=15)
parser.add_argument('--q-test', default=1)
args = parser.parse_args()

evaluation_episodes = 1000
episodes_per_epoch = 100

if args.dataset == 'omniglot':
    n_epochs = 40
    dataset_class = OmniglotDataset
    num_input_channels = 1
    drop_lr_every = 20
elif args.dataset == 'miniImageNet':
    n_epochs = 40
    dataset_class = MiniImageNet
    num_input_channels = 3
    drop_lr_every = 40
else:
    raise(ValueError, 'Unsupported dataset')

param_str = f'proto_net_{args.dataset}_n={args.n_train}_k={args.k_train}_q={args.q_train}'


###################
# Create datasets #
###################
background = dataset_class('background')
background_tasks = NShotWrapper(background, episodes_per_epoch, args.n_train, args.k_train, args.q_train)
background_taskloader = DataLoader(background_tasks, batch_size=1, num_workers=4)
evaluation = dataset_class('evaluation')
evaluation_tasks = NShotWrapper(evaluation, evaluation_episodes, args.n_test, args.k_test, args.q_test)
evaluation_taskloader = DataLoader(evaluation_tasks, batch_size=1, num_workers=4)


#########
# Model #
#########
model = get_few_shot_encoder(num_input_channels)
model.to(device, dtype=torch.double)


############
# Training #
############
print(f'Training Prototypical network on {args.dataset}...')
optimiser = Adam(model.parameters(), lr=1e-3)
loss_fn = torch.nn.CrossEntropyLoss().cuda()


def lr_schedule(epoch, lr):
    # Drop lr every 2000 episodes
    if epoch % drop_lr_every == 0:
        return lr / 2
    else:
        return lr


callbacks = [
    EvaluateFewShot(
        eval_fn=proto_net_episode,
        num_tasks=evaluation_episodes,
        n_shot=args.n_test,
        k_way=args.k_test,
        q_queries=args.q_test,
        task_loader=evaluation_taskloader,
        prepare_batch=prepare_nshot_task(args.n_test, args.k_test, args.q_test)
    ),
    ModelCheckpoint(
        filepath=PATH + f'/models/{param_str}.torch',
        monitor=f'val_{args.n_test}-shot_{args.k_test}-way_acc'
    ),
    LearningRateScheduler(schedule=lr_schedule),
    CSVLogger(PATH + f'/logs/proto_nets/{param_str}.csv'),
]

fit(
    model,
    optimiser,
    loss_fn,
    epochs=n_epochs,
    dataloader=background_taskloader,
    prepare_batch=prepare_nshot_task(args.n_train, args.k_train, args.q_train),
    callbacks=callbacks,
    metrics=['categorical_accuracy'],
    fit_function=proto_net_episode,
    fit_function_kwargs={'n_shot': args.n_train, 'k_way': args.k_train, 'q_queries': args.q_train, 'train': True}
)
