from __future__ import division
import autograd.numpy as np
import autograd.numpy.random as npr
from autograd import grad
from autograd.scipy.misc import logsumexp
from autograd import grad, grad_and_aux
from autograd.util import getval
from data import load_mnist

from neural_net import init_random_params, neural_net_predict


### Vanilla neural net functions

def log_likelihood(params, inputs, targets):
    '''Like log_posterior in neural_net.py, but no prior (regularizer) term.'''
    logprobs = neural_net_predict(params, inputs)
    return np.sum(logprobs * targets)

### General utility functions

def sample_discrete_from_log(logprobs):
    '''Given an NxD array where each row stores the log probabilities of a
       finite density, return the NxD array of one-hot encoded samples from
       those densities.'''
    probs = np.exp(logprobs)
    cumvals = np.cumsum(probs, axis=1)
    indices = np.sum(npr.rand(logprobs.shape[0], 1) > cumvals, axis=1)
    return np.eye(logprobs.shape[1])[indices]

### K-FAC utility functions

# First, we need to augment the neural net computation to collect the required
# statistics, namely samples of the activations and samples of the gradients of
# those activations under random targets generated by the model.

def neural_net_predict_and_activations(extra_biases, params, inputs):
    '''Like the neural_net_predict function in neural_net.py,
       but (1) adds extra biases and (2) also returns all computed
       activations.'''
    all_activations = [inputs]
    for (W, b), extra_bias in zip(params, extra_biases):
        s = np.dot(all_activations[-1], W) + b + extra_bias
        all_activations.append(np.tanh(s))
    logprobs = s - logsumexp(s, axis=1, keepdims=True)
    return logprobs, all_activations[:-1]

def model_predictive_log_likelihood(extra_biases, params, inputs):
    '''Computes log_likelihood on targets sampled from the model.'''
    logprobs, activations = neural_net_predict_and_activations(
        extra_biases, params, inputs)
    model_sampled_targets = sample_discrete_from_log(getval(logprobs))
    return np.sum(logprobs * model_sampled_targets), activations

def collect_activations_and_grad_samples(params, inputs):
    '''Collects the statistics necessary to estimate the approximate Fisher
       information matrix used in K-FAC.'''
    extra_biases = [np.zeros((inputs.shape[0], b.shape[0])) for W, b in params]
    gradfun = grad_and_aux(model_predictive_log_likelihood)
    g_samples, a_samples = gradfun(extra_biases, params, inputs)
    return a_samples, g_samples

### Bookkeeping for samples

# These functions are just to help collect samples across multiple iterations.

def append_samples(all_samples, new_samples):
    '''Appends the newly-collected layerwise samples to the rest of the samples.
       Both all_samples and new_samples are lists of length num_layers,
       all_samples[0] is a list of all the samples for layer 0,
       all_samples[1] is a list of all the samples for layer 1, etc.
    '''
    for layer_samples, new_layer_samples in zip(all_samples, new_samples):
        layer_samples.append(new_layer_samples)

def init_sample_lists(layer_sizes):
    return [[[] for _ in layer_sizes[:-1]] for _ in range(2)]

### Bookkeeping for kron factor estimates

# These functions are for turning the collected samples into estimates of the
# Kronecker factors that we use to define the K-FAC preconditioner.

append_homog_coord = lambda x: np.hstack((x, np.ones((x.shape[0], 1))))
identity = lambda x: x

def estimate_block_kron_factors(all_samples, append_homog=False):
    '''Given a list of samples for each layer, estimates the second moment from
       the samples.'''
    num_samples = sum(samples.shape[0] for samples in all_samples[0])
    homog = append_homog_coord if append_homog else identity
    sumsq = lambda samples: np.dot(samples.T, samples)
    layer_sumsq = lambda layer_samples: \
        sum(map(sumsq, map(homog, layer_samples))) / num_samples
    return map(layer_sumsq, all_samples)

def update_factor_estimates(old_estimates, samples, eps=0.05):
    As, Gs = old_estimates
    a_samples, g_samples = samples
    Ahats = estimate_block_kron_factors(a_samples, append_homog=True)
    Ghats = estimate_block_kron_factors(g_samples)
    update = lambda old, new: eps*old + (1.-eps)*new
    return map(update, As, Ahats), map(update, Gs, Ghats)

def init_factor_estimates(layer_sizes):
    layer_sizes = np.array(layer_sizes)
    return map(np.eye, layer_sizes[:-1] + 1), map(np.eye, layer_sizes[1:])

### Computing and applying the preconditioner

# These functions compute the inverses of the Kronecker factors and apply the
# K-FAC preconditioner to parameter updates.

# TODO

### script

if __name__ == '__main__':
    # Model parameters
    layer_sizes = [784, 200, 100, 10]

    # Training parameters
    param_scale = 0.1
    batch_size = 256

    N, train_images, train_labels, test_images,  test_labels = load_mnist()

    params = init_random_params(param_scale, layer_sizes)

    num_batches = int(np.ceil(len(train_images) / batch_size))
    def batch_indices(itr):
        idx = itr % num_batches
        return slice(idx * batch_size, (idx+1) * batch_size)

    # Define training objective
    def objective(params, itr):
        idx = batch_indices(itr)
        return -log_likelihood(params, train_images[idx], train_labels[idx])[0]

    # TODO in-progress stuff below, just for testing

    def collect_samples(params, itr):
        batch = train_images[batch_indices(itr)]
        new_samples = collect_activations_and_grad_samples(params, batch)
        map(append_samples, all_samples, new_samples)


    # initialize K-FAC side info
    all_samples = init_sample_lists(layer_sizes)
    factor_estimates = init_factor_estimates(layer_sizes)

    # collect new samples
    collect_samples(params, 0)
    collect_samples(params, 1)
    collect_samples(params, 2)

    # update factor estimates
    factor_estimates = update_factor_estimates(factor_estimates, all_samples)
    all_samples = init_sample_lists(layer_sizes)
