import torch
import numpy as np

class EnsemblePursuitPyTorch():
    
    def zscore(self):
        mean_stimuli=self.X.mean(dim=0)
        std_stimuli=self.X.std(dim=0)+0.0000000001
        
        self.X=torch.sub(self.X,mean_stimuli)
        self.X=self.X.div(std_stimuli)

    def calculate_cost_delta(self):
        cost_delta=torch.clamp(self.C_summed,min=0,max=None)**2/(self.sz[0]*torch.matmul(self.current_v,self.current_v))-self.lambd
        return cost_delta
    
    def fit_one_assembly(self):
        '''
        Function for fitting one cell assembly and computing u and v of the currrent assembly (self.current_u,
        self.current_v).
        '''
        with torch.cuda.device(0) as device:
            self.C=torch.matmul(self.X.t(),self.X)
            self.n=1       
            min_assembly_size=self.neuron_init_dict['parameters']['min_assembly_size']
            max_delta_cost=1000
            safety_it=0
            while self.n<min_assembly_size:
                seed=self.select_seed()
                #Array of keeping track of neurons in the cell assembly
                self.selected_neurons=torch.zeros([self.sz[1]]).type(torch.ByteTensor)
                self.selected_neurons[seed]=1
                #Seed current_v
                self.current_v=self.X[:,seed].flatten()
                #Fake cost to initiate while loop
                max_delta_cost=1000
                #reset i
                self.n=1
                self.neuron_lst=[seed]
                max_delta_cost=1000
                while max_delta_cost>0:
                    self.C_summed=(1./self.n)*torch.sum(self.C[:,self.selected_neurons],dim=1)
                    cost_delta=self.calculate_cost_delta()
                    #invert the 0's and 1's in the array which stores which neurons have already 
                    #been selected into the assembly to use it as a mask
                    mask=self.selected_neurons.clone().type(torch.cuda.FloatTensor)
                    mask[self.selected_neurons==0]=1
                    mask[self.selected_neurons!=0]=0
                    masked_cost_delta=mask*cost_delta
                    values,sorted_neurons=masked_cost_delta.sort()
                    max_delta_neuron=sorted_neurons[-1]
                    max_delta_cost=values[-1]
                    if max_delta_cost>0:
                        self.selected_neurons[max_delta_neuron.item()]=1
                        self.current_v= self.X[:, (self.selected_neurons == 1)].mean(dim=1)
                        self.neuron_lst.append(max_delta_neuron.item())
                        self.n+=1
                safety_it+=1
                #Increase number of neurons to sample from if while loop hasn't been finding any assemblies.     
                if safety_it>1:
                    self.n_neurons=10
                if safety_it>100:
                    self.n_neurons=500
                if safety_it>600:
                    self.n_neurons=1000
                if safety_it>1600:
                    raise ValueError('Assembly capacity too big, can\'t fit model')
            self.seed_neurons=self.seed_neurons+[seed]
            self.current_u=torch.clamp(self.C_summed,min=0,max=None)/torch.matmul(self.current_v,self.current_v)
            self.ensemble_neuron_lst.append(self.neuron_lst)
            self.U=torch.cat((self.U,self.current_u.view(self.X.size(1),1)),1)
            self.V=torch.cat((self.V,self.current_v.view(1,self.X.size(0))),0)

    
    def select_seed(self):
        '''
        Finds n_neurons neurons that are on average most correlated to their 
        n_av_neurons closest neighbors.
        '''
        n_av_neurons=self.neuron_init_dict['parameters']['n_av_neurons']
        #Sorts each row of correlation matrix
        vals,ix=self.C.sort(dim=1)
        #Discards the last entry corresponding to the diagonal 1 and then
        #selects n_av_neurons of the largest entries from sorted array.
        top_vals=vals[:,:-1][:,self.sz[1]-n_av_neurons:]
        #Averages the 5 top correlations.
        av=torch.mean(top_vals,dim=1)
        #Sorts the averages
        vals,top_neurons=torch.sort(av)
        #Selects top neurons
        #top_neuron=top_neurons[-1]
        top_neurons=top_neurons[self.sz[1]-(self.n_neurons+1):]
        idx=torch.randint(0,self.n_neurons,size=(1,))
        top_neuron=top_neurons[idx[0]].item()
        return top_neuron
    
    
    def fit_transform(self,X,lambd,n_ensembles,neuron_init_dict):
        torch.manual_seed(7)
        with torch.cuda.device(0) as device:
            self.ensemble_neuron_lst=[]
            self.neuron_init_dict=neuron_init_dict
            self.lambd=lambd
            #Creates cuda tensor from data
            self.X=torch.cuda.FloatTensor(X)
            #z-score data.
            self.zscore()
            #Store dimensionality of X for later use.
            self.sz=self.X.size()
            #print('sz',self.sz)
            #Initializes U and V with zeros, later these will be discarded.
            self.U=torch.zeros((self.X.size(1),1)).cuda()
            self.V=torch.zeros([1,self.X.size(0)]).cuda()
            #List for storing the number of neurons in each fit assembly.
            self.nr_of_neurons=[]
            #List for storing the seed neurons for each assembly.
            self.seed_neurons=[]
            cost_lst=[]
            #a variable to switch to random initialization after finding first assembly if the method is
            #selecting neurons from a time point
            self.first_assembly=True
            seeds=np.load('/home/maria/Documents/natimg2800_M170717_MP034_2017-09-11.mat_n_av_n_100_0.03_150_seed_neurons.npy')
            for iteration in range(0,n_ensembles):
                #self.seed=seeds[iteration]
                self.n_neurons=self.neuron_init_dict['parameters']['n_of_neurons']
                self.fit_one_assembly()
                self.nr_of_neurons.append(self.n)
                U_V=torch.mm(self.current_u.view(self.sz[1],1),self.current_v.view(1,self.sz[0]))
                U_V[U_V != U_V] = 0
                self.X=(self.X-U_V.t())
                print('ensemble nr', iteration)
                #print('u',self.current_u)
                #print('v',self.current_v)
                #print('length v', torch.matmul(self.current_v,self.current_v))
                #print('norm',torch.norm(self.X))
                self.cost=torch.mean(torch.mul(self.X,self.X))
                print('cost',self.cost)
                cost_lst.append(self.cost.item())
            #After fitting arrays discard the zero initialization rows and columns from U and V.
            self.U=self.U[:,1:]
            self.V=self.V[1:,:]
            #print(self.X.size())
            #print(self.U.size())
            #print(self.V.size())
            return torch.matmul(self.U,self.V).t().cpu(), self.nr_of_neurons, self.U.cpu(), np.array(self.V.cpu()).T, cost_lst, self.seed_neurons, self.ensemble_neuron_lst 



            
